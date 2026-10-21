# Segmented, resumable downloads — design

**Date:** 2026-10-21
**Status:** Draft for review
**Scope:** The per-file transfer in `src/downloaders/`, its config knobs (env, CLI, web), and the web Settings panel. Album-level concurrency, crawling, signing and the event contract are unchanged.

## Goal

1. **Faster single-file transfer**: split a large file into N byte ranges fetched in parallel and written into one pre-sized temp file. Measured on Bunkr's CDN from a residential link: 1 stream ≈ 20 MB/s, 4 ranges ≈ 35 MB/s.
2. **Resume broken downloads**: a transfer interrupted by a network error, an expired signed URL, a cancelled job, a container restart, or a host crash continues from the bytes already on disk — both on the next retry inside the same job and on a later run of the same album/file URL.
3. **Knobs in the web Settings panel**, with env values acting as the default when set, and built-in defaults otherwise. The value sent with each job wins.

## Non-goals

- No change to how many files run at once (`max_workers` stays as is).
- No checksum verification: Bunkr's CDN publishes none. Integrity is "size matches and ETag unchanged".
- No change to the CLI batch mode semantics (`main.py`) beyond the new flags being accepted.
- No download queue persistence across restarts: the *job* is still lost on restart; the *bytes* are not.

## Measured facts the design relies on

| Fact | Evidence (2026-10-21) |
|---|---|
| CDN supports ranges | `HEAD` → `Accept-Ranges: bytes`, `Content-Length` present; `GET` with `Range: bytes=1000000-1999999` → `206`, `Content-Range: bytes 1000000-1999999/1428977356` |
| CDN server | `Server: Angie` (nginx fork); ETag behaviour to be confirmed during implementation — if absent, size alone gates resume (see §Resume validation) |
| Signed URLs expire | `?token=…&ex=<epoch>` ≈ 2 h ahead; the album retry pass already re-resolves via the item page |
| Parallel gain | 2 ranges ≈ +5 %, 4 ranges ≈ +75 % on one 1.4 GB file |

## Architecture

### Components

```
MediaDownloader.attempt_download            (src/downloaders/media_downloader.py)
   └─ probe_remote(url, headers)            NEW  download_utils: HEAD → RemoteInfo(size, etag, accepts_ranges)
   └─ plan_transfer(remote, settings, manifest?)  NEW: decides single-stream vs segmented, builds/loads Manifest
   └─ SegmentedDownloader.run()             NEW  download_utils: N range workers + manifest flush + progress agg
        └─ ConnectionGovernor               NEW  process-wide BoundedSemaphore(MAX_CONCURRENT_CONNECTIONS)
   └─ save_file_with_progress(...)          EXISTING single-stream path, gains Range-resume from temp size
   └─ _finalise_download(...)               EXISTING: size check + rename; now also deletes the manifest
```

`DownloadOutcome` (SUCCESS / RETRYABLE_FAILURE / TERMINAL_FAILURE) stays the boundary contract; `AlbumDownloader` and the retry pass are untouched except for passing the new settings through `SessionInfo.args`.

### On-disk layout

For final path `<dir>/<name>.mp4`:

- `<dir>/<name>.temp` — the data file, **pre-sized to `size` with `truncate()`** (sparse on filesystems that support it; on CIFS/SMB shared folders this is a cheap metadata op in practice). Workers write at absolute offsets using `os.pwrite` on one shared file descriptor, so no locking is needed on the data path.
- `<dir>/<name>.temp.parts` — the **manifest**, JSON, written atomically (write to `.parts.tmp` + `os.replace`):

```json
{
  "version": 1,
  "url_origin": "https://bunkr.cr/f/IXUVhmTpJ5Qsi",
  "size": 1428977356,
  "etag": "\"6714a1c2-552f5b4c\"",
  "segment_size": 357244339,
  "segments": [
    {"start": 0,          "end": 357244338,  "done": 357244339},
    {"start": 357244339,  "end": 714488677,  "done": 120000000},
    {"start": 714488678,  "end": 1071733016, "done": 0},
    {"start": 1071733017, "end": 1428977355, "done": 0}
  ],
  "updated_at": "2026-10-21T02:11:09Z"
}
```

`done` is bytes written **contiguously from `start`**; a segment never has holes because each worker writes sequentially within its range. The manifest is flushed after every `MANIFEST_FLUSH_BYTES` (constant, 8 MiB) per segment and on worker exit, so a crash loses at most that much per segment, never correctness (bytes beyond `done` are simply re-fetched).

Single-stream transfers (small files, or no range support) keep today's `.temp` and write a minimal manifest with one segment, so they resume the same way.

`.temp` without a `.parts` file (left by builds before this change) is treated as **unknown and discarded**, as today.

### Decision: segmented or single stream

```
remote = probe_remote(url)            # one HEAD with the same headers as the GET
if remote.size is None or not remote.accepts_ranges:        → single stream, no resume (as today)
elif settings.segments <= 1 or remote.size < settings.segment_min_bytes: → single stream, resumable (1-segment manifest)
else: n = min(settings.segments, ceil(remote.size / settings.segment_min_bytes))   # never below min size per segment
      → segmented with n workers
```

The HEAD probe replaces today's *conditional* HEAD used only when the GET lacks `Content-Length`; it runs once per file, before the GET, and reuses the existing `_resolve_content_length` request plumbing (same UA/Referer).

### Resume validation

On start, if `<name>.temp.parts` exists:

1. Parse; reject (delete both files, start fresh, log one line) if `version` mismatches or the JSON is malformed.
2. `probe_remote(url)`; the local manifest is **valid** when `remote.size == manifest.size` **and** (`remote.etag is None` or `manifest.etag is None` or `remote.etag == manifest.etag`). Weak ETags (`W/`) compare by value.
3. Valid → continue each segment from `start + done`. Invalid → discard and start fresh.

`url_origin` (the item page, when known) is informational and lets a future tool re-sign an orphaned partial; it is not used for validation because the signed CDN URL itself changes every run.

### Segment workers

Each worker: `GET` with `Range: bytes=<start+done>-<end>`, expect `206` with a matching `Content-Range`; stream chunks (chunk size from existing `THRESHOLDS`, applied to the *segment* length) and `pwrite` at the running offset; update the shared progress counter under a lock; bump `done` and schedule a manifest flush.

Error handling per worker, mirroring `MediaDownloader._handle_request_exception` semantics:

| Condition | Action |
|---|---|
| `200` instead of `206` | Server ignored Range → abort segmented mode for this file, fall back to single stream **from offset 0** (manifest reset) |
| `416` | Our offsets disagree with the server → treat manifest as invalid, restart fresh |
| `403` on a URL with `ex=` in the past, or any `401/403` | Token expired → raise `LinkExpired`; the file-level loop asks `refresh_link()` (new callback supplied by `MediaDownloader`, which re-fetches the item page via `get_download_info`) and **restarts all workers with the new URL and the same manifest** |
| `ChunkedEncodingError`, `ReadTimeout`, `ConnectionError` | Segment retries in place with the existing exponential backoff, up to `retries`; manifest keeps what was written |
| `5xx` | Same as today's status-page/maintenance path at file level: the segmented run returns `RETRYABLE_FAILURE` and the album retry pass handles it |
| Disk `OSError` (ENOSPC, EIO) | `TERMINAL_FAILURE`, manifest kept (the user can free space and rerun) |

The file-level result is SUCCESS only when every segment's `done == length`; `_finalise_download` then asserts the file size, renames, and deletes the manifest.

### Connection governor

`ConnectionGovernor` is a module-level `threading.BoundedSemaphore(MAX_CONCURRENT_CONNECTIONS)` acquired for the lifetime of each streaming GET (segment or single). With defaults, 3 workers × 4 segments = 12 requested, cap 12. When the cap is lower than the demand, segments simply wait; nothing deadlocks because each worker holds at most one permit and the semaphore is sized ≥ `max_workers` at job start (enforced: effective cap = `max(cap, max_workers)`, logged once if raised).

### Progress

One task row per file, as today. `completed` = total bytes across segments ÷ size × 100, emitted through the existing `_emit_progress` throttle. The log pane gets one line when a file starts segmented (`"Segmented download: 4 × 340.7 MB"`) and one when it resumes (`"Resuming <name>: 61 % already on disk"`), both via `update_log`; no new event types, so the web event contract and `events.ts` are unchanged.

### Stale partial cleanup

Partials persist across runs by design. A guard against unbounded accumulation: at job start, `AlbumDownloader` scans the album directory for `*.temp.parts` older than `PARTIAL_MAX_AGE_HOURS` (default 168 = 7 days, 0 disables) and deletes them with their `.temp`, logging one line per file. Nothing is deleted while a job is running against that directory.

## Configuration

### Knobs

| Name | Default | Clamp | Meaning |
|---|---|---|---|
| `DOWNLOAD_SEGMENTS` | 4 | 1–16 | Parallel ranges per file; 1 = single stream (still resumable) |
| `SEGMENT_MIN_FILE_SIZE_MB` | 32 | 1–4096 | Files smaller than this are single-stream; also the minimum size per segment |
| `MAX_CONCURRENT_CONNECTIONS` | 12 | 1–64 | Process-wide cap on simultaneous streaming GETs |
| `PARTIAL_MAX_AGE_HOURS` | 168 | 0–8760 | Delete abandoned `.temp`/`.parts` older than this at job start; 0 disables |

All four follow the existing pattern: read in `src/config.py` via `_env_int_clamped`, forwarded in `docker-compose.yml` and `docker-compose.vpn.yml`, documented in `.env.sample` and the README Environment Variables table, and exposed as CLI flags `--segments`, `--segment-min-size-mb`, `--max-connections`, `--partial-max-age-hours` in `add_common_arguments`.

### Precedence (what "env settings only used if present" means in code)

```
built-in default  <  env var (if set)  <  value sent with the job (web form / CLI flag)
```

- `src/config.py` resolves `built-in < env` at import; those become the argparse defaults and the Pydantic defaults.
- `GET /api/settings/defaults` gains a `download` section returning the resolved values (`segments`, `segment_min_file_size_mb`, `max_concurrent_connections`, `partial_max_age_hours`, plus `max_workers` for completeness).
- `DownloadRequest` gains the same four optional fields (validated with the same clamps). `_build_namespace` copies them into the `Namespace`; absent fields fall back to the resolved defaults, so an old client that omits them behaves exactly as the env dictates.
- `MediaDownloader` reads them from `session_info.args` with the resolved default as fallback, never from `config` constants directly — the same rule the project applies to `max_workers` and `maintenance_strategy`.

### Web Settings panel

`SettingsPanel` gets a **Transfer** group with four numeric inputs (segments, min size MB, max connections, partial max age hours), each with a tooltip stating the clamp and what it does, matching the existing `maxWorkers` control. On first load, `App.tsx` fetches `/api/settings/defaults` and seeds **only the keys the user has never saved** (persisted settings live in `localStorage` under `bunkrdownloader:settings`); a "Reset to server defaults" button re-seeds the Transfer group. `DownloadForm` sends the four values with every job. Fixing the pre-existing gap for the network fields (they also never read server defaults) is **out of scope** here but the seeding helper is written generically so it can be applied to them later.

## Data flow (one file, segmented, resumed after a token expiry)

1. `AlbumDownloader` resolves item → `MediaDownloader.download()` → `_skip_file_download` (final file exists? no).
2. `attempt_download`: `probe_remote` → size 1.43 GB, ranges OK, ETag `"abc"`. Manifest exists with same size/ETag, segments 1–2 partially done → log "Resuming …".
3. `SegmentedDownloader.run()` starts 4 workers; each acquires a governor permit, issues its Range GET, pwrites, flushes manifest periodically.
4. 40 minutes in, the CDN answers `403` (token `ex` passed). Workers raise `LinkExpired`; the run returns `NEEDS_REFRESH` internally; `attempt_download` calls `refresh_link()` → new signed URL → `run()` again with the same manifest; workers continue from their `done` offsets.
5. All segments complete → `_finalise_download` checks `st_size == size`, renames to `.mp4`, deletes `.parts`, task → 100 %.

## Error handling summary (file level)

| Outcome | When | Album behaviour |
|---|---|---|
| `SUCCESS` | all bytes present, rename OK | next file |
| `RETRYABLE_FAILURE` | network/5xx exhaustion, short size at finalise | queued for the retry pass (re-resolves URL, then resumes from manifest) |
| `TERMINAL_FAILURE` | disk error, `416` twice in a row, manifest repeatedly invalid | logged to `session.log`, skipped |

Cancellation (`job.task.cancel()`) propagates as today through `asyncio.to_thread`; workers see the shared `cancel_event` checked between chunks and exit, leaving a consistent manifest — which is exactly what makes a later run resume.

## Testing

Unit (`tests/unit/test_segmented_download.py`, fixtures under `tests/fixtures/`):
- `plan_transfer` decisions: no size / no ranges / below threshold / `segments=1` / normal; segment boundary math has no gaps or overlaps and covers `[0, size)` exactly, including sizes not divisible by `n`.
- Manifest round-trip, atomic write, malformed/old-version rejection, validation matrix (size/etag combinations).
- `SegmentedDownloader` against a fake HTTP layer (`responses` or a tiny `http.server` thread serving a 5 MB random file with Range support): full transfer, resume after kill at 40 %, `200`-instead-of-`206` fallback, `416` → fresh start, `403` → `refresh_link` called and transfer completes, cancellation leaves a valid manifest, final bytes equal the source (hash compare).
- Governor: with cap 2 and 4 segments, never more than 2 concurrent in-flight (assert via a counter in the fake server).
- Config: env default/clamp/garbage for the four knobs; `_build_namespace` precedence (absent field → env default; present field → wins).
- Web: `DownloadRequest` validation (clamps), `/api/settings/defaults` shape.

Existing suites must stay green: `test_download_utils`, `test_media_downloader`, `test_review_regressions`, the integration job flow.

Manual/real: one album on the dev box with `DOWNLOAD_SEGMENTS=4`, kill the process mid-file, rerun, confirm resume log line and byte-identical result versus a single-stream download of the same file.

## Rollout

- One PR, `feat(download): segmented, resumable transfers` → semantic-release minor (v0.14.x; the re-attach PR lands first as v0.14.0 if merged before this).
- README: new "Transfer" subsection under Configuration (how resume works, where partials live, cleanup rule), the four table rows, and a Latest Release Updates entry after release.
- CLAUDE.md: update the `src/downloaders/` bullet (manifest format, governor, resume rules) and the knobs list.
- Compose files: forward the four env vars.

## Risks and mitigations

- **More connections → Bunkr IP blocks.** Default cap 12 equals today's worst case of 3 workers × (1 GET + 1 HEAD + retries). Documented; the VPN variant mitigates.
- **Sparse pre-size on SMB shared folders.** If `truncate()` is slow or unsupported, fall back to writing segments into the file as they arrive (seek+write) — correctness is unaffected because offsets are absolute. Tested on the NAS during rollout.
- **Partial files visible to users in the share.** They already are (`.temp`); the `.parts` sidecar is new but tiny. Cleanup rule bounds them.
