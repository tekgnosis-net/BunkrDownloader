# Segmented, Resumable Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download large files as N parallel byte ranges into one pre-sized temp file, and resume any interrupted transfer (same job or a later run) from a small on-disk manifest, with the knobs exposed via env, CLI and the web Settings page.

**Architecture:** A `TransferManifest` (`<name>.temp.parts`, JSON) records remote size/ETag and per-segment progress; `SegmentedDownloader` runs range workers that `pwrite` into `<name>.temp` and flush the manifest; `MediaDownloader.attempt_download` probes the remote once (HEAD), plans single vs segmented, validates/loads an existing manifest, and handles expired signed URLs by re-resolving the item page and restarting workers against the same manifest. A process-wide `ConnectionGovernor` caps simultaneous streaming GETs. Settings resolve `built-in < env < per-job`.

**Tech Stack:** Python ≥3.10 (`requests`, `threading`, `os.pwrite`), FastAPI/Pydantic (web), React 18 + Chakra UI 2 + TypeScript (settings UI), pytest with a local range-capable `http.server` fixture.

**Spec:** `docs/superpowers/specs/2026-10-21-segmented-resumable-downloads-design.md`

## Global Constraints

- Python ≥ 3.10; `from __future__ import annotations` in every new module.
- Pylint must stay at 10.00/10 with zero messages (CI runs `python -m pylint $(git ls-files '*.py')`); pytest has a 30 s per-test timeout.
- Every threshold is an env knob with default + clamp, forwarded in **both** compose files, listed in `.env.sample` and the README table. Exact knobs: `DOWNLOAD_SEGMENTS` (4, 1–16), `SEGMENT_MIN_FILE_SIZE_MB` (32, 1–4096), `MAX_CONCURRENT_CONNECTIONS` (12, 1–64), `PARTIAL_MAX_AGE_HOURS` (168, 0–8760).
- Precedence: built-in default < env var (if set) < value sent with the job (web field / CLI flag).
- `DownloadOutcome` (`SUCCESS / RETRYABLE_FAILURE / TERMINAL_FAILURE`) remains the contract between `MediaDownloader` and `AlbumDownloader`. No new web event types; `frontend/src/lib/events.ts` is untouched.
- Manifest flush cadence constant: 8 MiB per segment (`MANIFEST_FLUSH_BYTES`).
- On-disk names: data `<final>.temp` (existing), manifest `<final>.temp.parts` (new). A `.temp` without a `.parts` is discarded as today.
- Conventional Commits; branch `feat/segmented-resumable-downloads` already exists with the spec; final PR title `feat(download): segmented, resumable transfers`.
- Never print secrets; never stage `.remember/`, `.playwright-mcp/`, `supertool`, `pr3-*.png`.

## Review Focus

1. **Remote size changed between runs (same name, new upload).** Expected: manifest rejected, partial discarded, fresh download — never a file stitched from two versions. Pinned in Task 2 (`test_manifest_mismatch_on_size`) and Task 9 (`test_attempt_download_discards_mismatched_manifest`).
2. **Server answers `200` to a Range request (ranges silently unsupported).** Expected: fall back to a single stream from byte 0, no corrupted interleaving. Pinned in Task 7 (`test_segmented_falls_back_when_server_ignores_range`).
3. **Disk full mid-transfer on the NAS.** Expected: `TERMINAL_FAILURE`, manifest kept so the user can free space and resume; no infinite retry loop. Pinned in Task 7 (`test_segmented_disk_error_is_terminal_and_keeps_manifest`).
4. **Cancel while segments are mid-write.** Expected: workers stop within one chunk, manifest on disk is consistent, a later run resumes. Pinned in Task 7 (`test_segmented_cancel_leaves_resumable_manifest`).
5. **Env var set to garbage or out of range (`DOWNLOAD_SEGMENTS=lots`, `=99`).** Expected: default / clamped value, no crash at import. Pinned in Task 1 (`test_transfer_knobs_env_default_and_clamp`).

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/config.py` (modify) | four knobs, `TransferSettings`, `resolve_transfer_settings(args)`, CLI flags |
| `src/downloaders/transfer_manifest.py` (create) | `Segment`, `TransferManifest`, plan/save/load/validate/discard |
| `src/downloaders/remote_probe.py` (create) | `RemoteInfo`, `probe_remote` (one HEAD), `normalise_etag` |
| `src/downloaders/connection_governor.py` (create) | process-wide in-flight cap |
| `src/downloaders/segmented_download.py` (create) | `plan_transfer`, `SegmentedDownloader`, `SegmentedOutcome`, `cleanup_stale_partials` |
| `src/downloaders/download_utils.py` (modify) | single-stream resume (`resume_from`, manifest upkeep), manifest removal on finalise |
| `src/downloaders/media_downloader.py` (modify) | orchestration: probe → validate manifest → plan → run; link refresh |
| `src/downloaders/album_downloader.py` (modify) | stale-partial cleanup at job start |
| `src/web/app.py` (modify) | `DownloadRequest` fields, `_build_namespace`, `/api/settings/defaults` `download` section |
| `frontend/src/App.tsx`, `components/settings/SettingsPanel.tsx`, `components/download/DownloadForm.tsx` (modify) | Transfer settings group, server-default seeding, payload |
| `tests/helpers/range_server.py` (create) | local HTTP server with Range support and fault injection |
| `tests/unit/test_transfer_settings.py`, `test_transfer_manifest.py`, `test_remote_probe.py`, `test_connection_governor.py`, `test_segmented_download.py`, `test_media_downloader_transfer.py`, `test_album_partial_cleanup.py`, `test_web_transfer_settings.py` (create); `tests/unit/test_download_utils.py` (modify) | tests |
| `README.md`, `.env.sample`, `docker-compose.yml`, `docker-compose.vpn.yml`, `CLAUDE.md` (modify) | docs and forwarding |

---

### Task 1: Transfer knobs, `TransferSettings`, CLI flags

**Files:**
- Modify: `src/config.py` (after `MAINTENANCE_BACKOFF_DELAYS_SECONDS`, and inside `add_common_arguments`)
- Test: `tests/unit/test_transfer_settings.py`

**Interfaces:**
- Produces:
  ```python
  DOWNLOAD_SEGMENTS: int; SEGMENT_MIN_FILE_SIZE_MB: int; MAX_CONCURRENT_CONNECTIONS: int; PARTIAL_MAX_AGE_HOURS: int
  @dataclass(frozen=True)
  class TransferSettings: segments: int; segment_min_bytes: int; max_connections: int; partial_max_age_hours: int
  def resolve_transfer_settings(args: Namespace | None) -> TransferSettings
  ```
  CLI flags with `dest`: `--segments` → `segments`, `--segment-min-size-mb` → `segment_min_size_mb`, `--max-connections` → `max_connections`, `--partial-max-age-hours` → `partial_max_age_hours`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_transfer_settings.py
"""Transfer knobs: env defaults/clamps, per-job precedence, CLI flags."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

import importlib
from argparse import ArgumentParser, Namespace

import pytest


def _reload_config():
    from src import config  # pylint: disable=import-outside-toplevel
    return importlib.reload(config)


@pytest.mark.parametrize(
    ("env", "attr", "expected"),
    [
        ({}, "DOWNLOAD_SEGMENTS", 4),
        ({"DOWNLOAD_SEGMENTS": "99"}, "DOWNLOAD_SEGMENTS", 16),
        ({"DOWNLOAD_SEGMENTS": "0"}, "DOWNLOAD_SEGMENTS", 1),
        ({"DOWNLOAD_SEGMENTS": "lots"}, "DOWNLOAD_SEGMENTS", 4),
        ({}, "SEGMENT_MIN_FILE_SIZE_MB", 32),
        ({"SEGMENT_MIN_FILE_SIZE_MB": "0"}, "SEGMENT_MIN_FILE_SIZE_MB", 1),
        ({}, "MAX_CONCURRENT_CONNECTIONS", 12),
        ({"MAX_CONCURRENT_CONNECTIONS": "1000"}, "MAX_CONCURRENT_CONNECTIONS", 64),
        ({}, "PARTIAL_MAX_AGE_HOURS", 168),
        ({"PARTIAL_MAX_AGE_HOURS": "0"}, "PARTIAL_MAX_AGE_HOURS", 0),
    ],
)
def test_transfer_knobs_env_default_and_clamp(monkeypatch, env, attr, expected):
    for name in ("DOWNLOAD_SEGMENTS", "SEGMENT_MIN_FILE_SIZE_MB",
                 "MAX_CONCURRENT_CONNECTIONS", "PARTIAL_MAX_AGE_HOURS"):
        monkeypatch.delenv(name, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    try:
        assert getattr(_reload_config(), attr) == expected
    finally:
        for key in env:
            monkeypatch.delenv(key, raising=False)
        _reload_config()


def test_resolve_transfer_settings_defaults_when_args_missing():
    from src.config import resolve_transfer_settings  # pylint: disable=import-outside-toplevel
    settings = resolve_transfer_settings(None)
    assert settings.segments == 4
    assert settings.segment_min_bytes == 32 * 1024 * 1024
    assert settings.max_connections == 12
    assert settings.partial_max_age_hours == 168


def test_resolve_transfer_settings_per_job_wins_and_is_clamped():
    from src.config import resolve_transfer_settings  # pylint: disable=import-outside-toplevel
    args = Namespace(segments=8, segment_min_size_mb=5000, max_connections=0, partial_max_age_hours=None)
    settings = resolve_transfer_settings(args)
    assert settings.segments == 8
    assert settings.segment_min_bytes == 4096 * 1024 * 1024   # clamped to 4096 MB
    assert settings.max_connections == 1                      # clamped up to 1
    assert settings.partial_max_age_hours == 168              # None -> env/default


def test_cli_flags_registered_with_env_defaults():
    from src.config import add_common_arguments  # pylint: disable=import-outside-toplevel
    parser = ArgumentParser()
    add_common_arguments(parser)
    ns = parser.parse_args([])
    assert ns.segments == 4
    assert ns.segment_min_size_mb == 32
    assert ns.max_connections == 12
    assert ns.partial_max_age_hours == 168
    ns = parser.parse_args(["--segments", "2", "--segment-min-size-mb", "64",
                            "--max-connections", "6", "--partial-max-age-hours", "0"])
    assert (ns.segments, ns.segment_min_size_mb, ns.max_connections, ns.partial_max_age_hours) == (2, 64, 6, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_transfer_settings.py -q`
Expected: FAIL — `AttributeError: module 'src.config' has no attribute 'DOWNLOAD_SEGMENTS'` / `ImportError: cannot import name 'resolve_transfer_settings'`.

- [ ] **Step 3: Add the knobs and resolver to `src/config.py`**

Insert directly after the `MAINTENANCE_BACKOFF_DELAYS_SECONDS = ...` block:

```python
# ============================
# Transfer (segmented + resumable downloads)
# ============================
# Parallel byte ranges per file; 1 = single stream (still resumable).
DOWNLOAD_SEGMENTS = _env_int_clamped("DOWNLOAD_SEGMENTS", 4, 1, 16)
# Files smaller than this stay single-stream; also the minimum bytes per segment.
SEGMENT_MIN_FILE_SIZE_MB = _env_int_clamped("SEGMENT_MIN_FILE_SIZE_MB", 32, 1, 4096)
# Process-wide cap on simultaneous streaming GETs (workers x segments).
MAX_CONCURRENT_CONNECTIONS = _env_int_clamped("MAX_CONCURRENT_CONNECTIONS", 12, 1, 64)
# Abandoned .temp/.temp.parts older than this are deleted at job start; 0 disables.
PARTIAL_MAX_AGE_HOURS = _env_int_clamped("PARTIAL_MAX_AGE_HOURS", 168, 0, 8760)

_TRANSFER_CLAMPS: dict[str, tuple[int, int]] = {
    "segments": (1, 16),
    "segment_min_size_mb": (1, 4096),
    "max_connections": (1, 64),
    "partial_max_age_hours": (0, 8760),
}


@dataclass(frozen=True)
class TransferSettings:
    """Resolved per-job transfer knobs (built-in < env < per-job value)."""

    segments: int
    segment_min_bytes: int
    max_connections: int
    partial_max_age_hours: int


def _clamped_arg(args: Namespace | None, name: str, default: int) -> int:
    value = getattr(args, name, None) if args is not None else None
    if value is None:
        return default
    lower, upper = _TRANSFER_CLAMPS[name]
    try:
        return max(lower, min(upper, int(value)))
    except (TypeError, ValueError):
        return default


def resolve_transfer_settings(args: Namespace | None) -> TransferSettings:
    """Return the effective transfer settings for a job.

    Env-derived module constants are the defaults; any attribute present and
    non-``None`` on ``args`` (CLI flag or web request field) overrides it and
    is clamped to the same bounds.
    """
    return TransferSettings(
        segments=_clamped_arg(args, "segments", DOWNLOAD_SEGMENTS),
        segment_min_bytes=_clamped_arg(args, "segment_min_size_mb", SEGMENT_MIN_FILE_SIZE_MB) * MB,
        max_connections=_clamped_arg(args, "max_connections", MAX_CONCURRENT_CONNECTIONS),
        partial_max_age_hours=_clamped_arg(args, "partial_max_age_hours", PARTIAL_MAX_AGE_HOURS),
    )
```

`MB` is already defined in `config.py` (`MB = 1024 * KB`) — but it is defined **below** this point in the file today (`KB`/`MB`/`GB` sit just above `THRESHOLDS`). Move the three lines `KB = 1024`, `MB = 1024 * KB`, `GB = 1024 * MB` up to directly below the `import` block so they are available here. `dataclass` and `Namespace` are already imported in `config.py`.

Then append to `add_common_arguments`, after the `--maintenance-strategy` argument:

```python
    parser.add_argument(
        "--segments",
        type=int,
        default=DOWNLOAD_SEGMENTS,
        help="Parallel byte ranges per file, 1-16; 1 = single stream (default: %(default)s).",
    )
    parser.add_argument(
        "--segment-min-size-mb",
        type=int,
        default=SEGMENT_MIN_FILE_SIZE_MB,
        help="Files below this size (MB) use a single stream (default: %(default)s).",
    )
    parser.add_argument(
        "--max-connections",
        type=int,
        default=MAX_CONCURRENT_CONNECTIONS,
        help="Process-wide cap on simultaneous download connections (default: %(default)s).",
    )
    parser.add_argument(
        "--partial-max-age-hours",
        type=int,
        default=PARTIAL_MAX_AGE_HOURS,
        help="Delete abandoned partial downloads older than this at job start; 0 disables (default: %(default)s).",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_transfer_settings.py -q && .venv/bin/python -m pylint src/config.py tests/unit/test_transfer_settings.py`
Expected: all pass; pylint 10.00 with no messages.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/unit/test_transfer_settings.py
git commit -m "feat(config): transfer knobs, TransferSettings resolver and CLI flags"
```

---

### Task 2: Transfer manifest module

**Files:**
- Create: `src/downloaders/transfer_manifest.py`
- Test: `tests/unit/test_transfer_manifest.py`

**Interfaces:**
- Produces:
  ```python
  MANIFEST_VERSION = 1
  @dataclass class Segment: start: int; end: int; done: int = 0   # end inclusive
      length -> int; remaining -> int; complete -> bool; next_offset -> int
  @dataclass class TransferManifest:
      size: int; etag: str | None; segments: list[Segment]; url_origin: str | None = None
      @classmethod plan(cls, size, segment_count, *, etag, url_origin=None) -> TransferManifest
      bytes_done -> int; complete -> bool; to_dict() -> dict; from_dict(data) -> TransferManifest (classmethod)
  def manifest_path(temp_path: Path) -> Path            # <temp>.parts
  def save_manifest(manifest, path: Path) -> None       # atomic (tmp + os.replace)
  def load_manifest(path: Path) -> TransferManifest | None   # None when missing/malformed/version mismatch
  def manifest_matches_remote(manifest, *, size: int | None, etag: str | None) -> bool
  def discard_partial(temp_path: Path) -> None          # unlink temp + manifest, ignore missing
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_transfer_manifest.py
"""Manifest: segment math, atomic round-trip, validation, discard."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.downloaders.transfer_manifest import (
    MANIFEST_VERSION,
    TransferManifest,
    discard_partial,
    load_manifest,
    manifest_matches_remote,
    manifest_path,
    save_manifest,
)


@pytest.mark.parametrize(("size", "n"), [(10, 4), (1000, 3), (1024 * 1024 + 1, 16), (7, 7), (5, 1)])
def test_plan_covers_range_exactly_without_gaps_or_overlap(size, n):
    manifest = TransferManifest.plan(size, n, etag='"e"')
    segs = manifest.segments
    assert len(segs) == n
    assert segs[0].start == 0
    assert segs[-1].end == size - 1
    for prev, cur in zip(segs, segs[1:]):
        assert cur.start == prev.end + 1
    assert sum(s.length for s in segs) == size
    assert all(s.done == 0 for s in segs)
    assert manifest.bytes_done == 0 and not manifest.complete


def test_segment_progress_properties():
    seg = TransferManifest.plan(100, 2, etag=None).segments[1]   # 50..99
    assert (seg.start, seg.end, seg.length) == (50, 99, 50)
    seg.done = 20
    assert seg.remaining == 30 and seg.next_offset == 70 and not seg.complete
    seg.done = 50
    assert seg.complete and seg.remaining == 0


def test_save_and_load_round_trip_is_atomic(tmp_path: Path):
    temp = tmp_path / "video.temp"
    path = manifest_path(temp)
    assert path == tmp_path / "video.temp.parts"
    manifest = TransferManifest.plan(1000, 4, etag='"abc"', url_origin="https://bunkr.cr/f/x")
    manifest.segments[1].done = 120
    save_manifest(manifest, path)
    assert not (tmp_path / "video.temp.parts.tmp").exists()
    loaded = load_manifest(path)
    assert loaded is not None
    assert loaded.size == 1000 and loaded.etag == '"abc"' and loaded.url_origin == "https://bunkr.cr/f/x"
    assert [s.done for s in loaded.segments] == [0, 120, 0, 0]
    assert json.loads(path.read_text())["version"] == MANIFEST_VERSION


def test_load_rejects_missing_malformed_and_wrong_version(tmp_path: Path):
    path = tmp_path / "x.temp.parts"
    assert load_manifest(path) is None
    path.write_text("{not json")
    assert load_manifest(path) is None
    path.write_text(json.dumps({"version": 99, "size": 1, "etag": None, "segments": []}))
    assert load_manifest(path) is None
    path.write_text(json.dumps({"version": 1, "size": 1}))       # missing segments
    assert load_manifest(path) is None


def test_manifest_mismatch_on_size():
    manifest = TransferManifest.plan(1000, 2, etag='"a"')
    assert manifest_matches_remote(manifest, size=1000, etag='"a"')
    assert not manifest_matches_remote(manifest, size=1001, etag='"a"')
    assert not manifest_matches_remote(manifest, size=None, etag='"a"')


def test_manifest_etag_rules():
    manifest = TransferManifest.plan(1000, 2, etag='"a"')
    assert manifest_matches_remote(manifest, size=1000, etag=None)       # remote has none -> size only
    assert not manifest_matches_remote(manifest, size=1000, etag='"b"')
    assert manifest_matches_remote(manifest, size=1000, etag='W/"a"')    # weak compares by value
    no_etag = TransferManifest.plan(1000, 2, etag=None)
    assert manifest_matches_remote(no_etag, size=1000, etag='"zzz"')     # local has none -> size only


def test_discard_partial_removes_both_and_ignores_missing(tmp_path: Path):
    temp = tmp_path / "f.temp"
    temp.write_bytes(b"xx")
    manifest_path(temp).write_text("{}")
    discard_partial(temp)
    assert not temp.exists() and not manifest_path(temp).exists()
    discard_partial(temp)   # no raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_transfer_manifest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.downloaders.transfer_manifest'`.

- [ ] **Step 3: Implement the module**

```python
# src/downloaders/transfer_manifest.py
"""On-disk manifest that makes a partially downloaded file resumable.

``<final>.temp`` holds the bytes; ``<final>.temp.parts`` (this module) records
the remote size/ETag and, per segment, how many bytes have been written
contiguously from the segment start. Workers only ever append within their
own range, so ``done`` is always a prefix length — there are no holes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_VERSION = 1


@dataclass
class Segment:
    """Inclusive byte range ``[start, end]`` plus bytes completed from ``start``."""

    start: int
    end: int
    done: int = 0

    @property
    def length(self) -> int:
        """Total bytes in this segment."""
        return self.end - self.start + 1

    @property
    def remaining(self) -> int:
        """Bytes still to fetch."""
        return self.length - self.done

    @property
    def complete(self) -> bool:
        """Whether every byte of the segment is on disk."""
        return self.done >= self.length

    @property
    def next_offset(self) -> int:
        """Absolute file offset of the next byte to write."""
        return self.start + self.done


@dataclass
class TransferManifest:
    """Resumable-transfer state for one file."""

    size: int
    etag: str | None
    segments: list[Segment] = field(default_factory=list)
    url_origin: str | None = None

    @classmethod
    def plan(
        cls,
        size: int,
        segment_count: int,
        *,
        etag: str | None,
        url_origin: str | None = None,
    ) -> TransferManifest:
        """Split ``[0, size)`` into ``segment_count`` contiguous ranges.

        The first ``size % n`` segments are one byte longer so the ranges
        tile the file exactly for any size.
        """
        count = max(1, min(segment_count, size)) if size > 0 else 1
        base, extra = divmod(size, count)
        segments: list[Segment] = []
        start = 0
        for index in range(count):
            length = base + (1 if index < extra else 0)
            segments.append(Segment(start=start, end=start + length - 1))
            start += length
        return cls(size=size, etag=etag, segments=segments, url_origin=url_origin)

    @property
    def bytes_done(self) -> int:
        """Bytes on disk across all segments."""
        return sum(segment.done for segment in self.segments)

    @property
    def complete(self) -> bool:
        """Whether all segments are fully written."""
        return bool(self.segments) and all(segment.complete for segment in self.segments)

    def to_dict(self) -> dict:
        """Serialisable form (see spec §On-disk layout)."""
        return {
            "version": MANIFEST_VERSION,
            "url_origin": self.url_origin,
            "size": self.size,
            "etag": self.etag,
            "segment_size": self.segments[0].length if self.segments else 0,
            "segments": [
                {"start": s.start, "end": s.end, "done": s.done} for s in self.segments
            ],
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    @classmethod
    def from_dict(cls, data: dict) -> TransferManifest:
        """Inverse of :meth:`to_dict`; raises ``ValueError`` on bad shape."""
        if data.get("version") != MANIFEST_VERSION:
            raise ValueError("unsupported manifest version")
        segments = [
            Segment(start=int(s["start"]), end=int(s["end"]), done=int(s.get("done", 0)))
            for s in data["segments"]
        ]
        if not segments:
            raise ValueError("manifest has no segments")
        return cls(
            size=int(data["size"]),
            etag=data.get("etag"),
            segments=segments,
            url_origin=data.get("url_origin"),
        )


def manifest_path(temp_path: Path) -> Path:
    """Return the sidecar path for a ``.temp`` data file."""
    return temp_path.with_name(temp_path.name + ".parts")


def save_manifest(manifest: TransferManifest, path: Path) -> None:
    """Write the manifest atomically (temp file + ``os.replace``)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    os.replace(tmp, path)


def load_manifest(path: Path) -> TransferManifest | None:
    """Load a manifest, returning ``None`` when absent, malformed or outdated."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TransferManifest.from_dict(data)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _etag_value(etag: str | None) -> str | None:
    if etag is None:
        return None
    value = etag.strip()
    if value.startswith("W/"):
        value = value[2:]
    return value.strip('"') or None


def manifest_matches_remote(
    manifest: TransferManifest, *, size: int | None, etag: str | None,
) -> bool:
    """Whether local partial bytes may be trusted against the remote object.

    Size must match exactly. ETag must match when both sides have one
    (weak validators compare by value); either side lacking an ETag falls
    back to the size check alone because the CDN publishes no checksum.
    """
    if size is None or size != manifest.size:
        return False
    local, remote = _etag_value(manifest.etag), _etag_value(etag)
    if local is None or remote is None:
        return True
    return local == remote


def discard_partial(temp_path: Path) -> None:
    """Delete the data file and its manifest; missing files are not an error."""
    for path in (temp_path, manifest_path(temp_path)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_transfer_manifest.py -q && .venv/bin/python -m pylint src/downloaders/transfer_manifest.py tests/unit/test_transfer_manifest.py`
Expected: all pass; pylint clean.

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/transfer_manifest.py tests/unit/test_transfer_manifest.py
git commit -m "feat(download): transfer manifest for resumable partial files"
```

---

### Task 3: Remote probe (one HEAD per file)

**Files:**
- Create: `src/downloaders/remote_probe.py`
- Test: `tests/unit/test_remote_probe.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True) class RemoteInfo: size: int | None; etag: str | None; accepts_ranges: bool
  def probe_remote(url: str, headers: dict[str, str], *, timeout: float = 10.0) -> RemoteInfo
  ```
  Any `RequestException` or non-2xx → `RemoteInfo(None, None, False)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_remote_probe.py
"""HEAD probe: size/etag/range support extraction and failure shape."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

from unittest.mock import MagicMock

import requests

from src.downloaders import remote_probe


def _resp(status=200, **headers):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


def test_probe_parses_size_etag_and_ranges(monkeypatch):
    seen = {}

    def fake_head(url, **kwargs):
        seen.update(kwargs, url=url)
        return _resp(**{"Content-Length": "1428977356", "ETag": '"6714a1c2"', "Accept-Ranges": "bytes"})

    monkeypatch.setattr(remote_probe.requests, "head", fake_head)
    info = remote_probe.probe_remote("https://cdn.example/f.mp4", {"User-Agent": "ua"}, timeout=3)
    assert info.size == 1428977356 and info.etag == '"6714a1c2"' and info.accepts_ranges
    assert seen["headers"] == {"User-Agent": "ua"} and seen["timeout"] == 3 and seen["allow_redirects"] is True


def test_probe_without_ranges_or_length(monkeypatch):
    monkeypatch.setattr(remote_probe.requests, "head", lambda *a, **k: _resp(**{"Accept-Ranges": "none"}))
    info = remote_probe.probe_remote("u", {})
    assert info.size is None and info.etag is None and not info.accepts_ranges


def test_probe_failure_is_soft(monkeypatch):
    def boom(*_a, **_k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(remote_probe.requests, "head", boom)
    assert remote_probe.probe_remote("u", {}) == remote_probe.RemoteInfo(None, None, False)
    monkeypatch.setattr(remote_probe.requests, "head", lambda *a, **k: _resp(status=403))
    assert remote_probe.probe_remote("u", {}) == remote_probe.RemoteInfo(None, None, False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_remote_probe.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/downloaders/remote_probe.py
"""One HEAD request per file to learn size, ETag and Range support."""

from __future__ import annotations

from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class RemoteInfo:
    """What the server told us about the object before any GET."""

    size: int | None
    etag: str | None
    accepts_ranges: bool


_UNKNOWN = RemoteInfo(size=None, etag=None, accepts_ranges=False)


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def probe_remote(url: str, headers: dict[str, str], *, timeout: float = 10.0) -> RemoteInfo:
    """HEAD ``url`` with the same headers the GET will use.

    Returns :data:`RemoteInfo` with ``size=None`` / ``accepts_ranges=False``
    on any network error or non-2xx status so callers degrade to a plain
    single-stream download instead of failing the file.
    """
    try:
        response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException:
        return _UNKNOWN
    accept = str(response.headers.get("Accept-Ranges", "")).lower()
    return RemoteInfo(
        size=_positive_int(response.headers.get("Content-Length")),
        etag=response.headers.get("ETag") or None,
        accepts_ranges="bytes" in accept,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_remote_probe.py -q && .venv/bin/python -m pylint src/downloaders/remote_probe.py tests/unit/test_remote_probe.py`
Expected: pass, pylint clean.

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/remote_probe.py tests/unit/test_remote_probe.py
git commit -m "feat(download): HEAD probe for size, ETag and range support"
```

---

### Task 4: Connection governor

**Files:**
- Create: `src/downloaders/connection_governor.py`
- Test: `tests/unit/test_connection_governor.py`

**Interfaces:**
- Produces:
  ```python
  class ConnectionGovernor:
      def __init__(self, limit: int) -> None
      limit -> int; in_flight -> int
      def raise_limit(self, minimum: int) -> int        # never lowers; returns effective limit
      @contextmanager def slot(self, cancel_event: threading.Event | None = None) -> Iterator[None]
  GOVERNOR = ConnectionGovernor(MAX_CONCURRENT_CONNECTIONS)
  ```
  `slot()` blocks while `in_flight >= limit`, polling `cancel_event` every 0.2 s and raising `Cancelled` (defined here) when set.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_connection_governor.py
"""Governor caps concurrent slots, never lowers the cap below demand, honours cancel."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

import threading
import time

import pytest

from src.downloaders.connection_governor import Cancelled, ConnectionGovernor


def test_slot_caps_concurrency():
    gov = ConnectionGovernor(2)
    peak = 0
    lock = threading.Lock()

    def worker():
        nonlocal peak
        with gov.slot():
            with lock:
                peak = max(peak, gov.in_flight)
            time.sleep(0.05)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 2 and gov.in_flight == 0


def test_raise_limit_only_raises():
    gov = ConnectionGovernor(3)
    assert gov.raise_limit(2) == 3
    assert gov.raise_limit(5) == 5
    assert gov.limit == 5


def test_slot_wait_is_cancellable():
    gov = ConnectionGovernor(1)
    cancel = threading.Event()
    with gov.slot():
        cancel.set()
        with pytest.raises(Cancelled):
            with gov.slot(cancel_event=cancel):
                pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_connection_governor.py -q`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/downloaders/connection_governor.py
"""Process-wide cap on simultaneous streaming download connections."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from src.config import MAX_CONCURRENT_CONNECTIONS


class Cancelled(Exception):
    """Raised from :meth:`ConnectionGovernor.slot` when the job is cancelled while waiting."""


class ConnectionGovernor:
    """Counting gate: at most ``limit`` callers hold a slot at once.

    Implemented with a condition variable rather than a semaphore so the
    limit can be raised at job start (``max(limit, max_workers)``) without
    recreating the object every worker already references.
    """

    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._in_flight = 0
        self._cond = threading.Condition()

    @property
    def limit(self) -> int:
        """Current cap."""
        return self._limit

    @property
    def in_flight(self) -> int:
        """Slots currently held."""
        return self._in_flight

    def raise_limit(self, minimum: int) -> int:
        """Ensure the cap is at least ``minimum``; return the effective cap."""
        with self._cond:
            if minimum > self._limit:
                self._limit = int(minimum)
                self._cond.notify_all()
            return self._limit

    @contextmanager
    def slot(self, cancel_event: threading.Event | None = None) -> Iterator[None]:
        """Hold one connection slot for the duration of the ``with`` block."""
        with self._cond:
            while self._in_flight >= self._limit:
                if cancel_event is not None and cancel_event.is_set():
                    raise Cancelled()
                self._cond.wait(timeout=0.2)
            self._in_flight += 1
        try:
            yield
        finally:
            with self._cond:
                self._in_flight -= 1
                self._cond.notify()


GOVERNOR = ConnectionGovernor(MAX_CONCURRENT_CONNECTIONS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_connection_governor.py -q && .venv/bin/python -m pylint src/downloaders/connection_governor.py tests/unit/test_connection_governor.py`
Expected: pass, pylint clean.

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/connection_governor.py tests/unit/test_connection_governor.py
git commit -m "feat(download): process-wide connection governor"
```

---

### Task 5: Range-capable test HTTP server with fault injection

**Files:**
- Create: `tests/helpers/__init__.py` (empty), `tests/helpers/range_server.py`
- Modify: `tests/conftest.py` (add `range_server` fixture)

**Interfaces:**
- Produces fixture `range_server` → `RangeServer` with:
  ```python
  rs.url                     # http://127.0.0.1:<port>/file.bin
  rs.data: bytes             # 5 MiB pseudo-random, deterministic seed
  rs.etag: str               # '"test-etag-1"'
  rs.ignore_range: bool      # answer 200 + full body to Range requests
  rs.forbid_from_request: int | None   # Nth GET onward -> 403
  rs.abort_once_after: int | None      # first GET: close socket after N body bytes
  rs.no_ranges: bool         # omit Accept-Ranges, ignore Range
  rs.peak_in_flight: int     # max simultaneous GETs observed
  rs.get_count: int
  rs.reset()
  ```

- [ ] **Step 1: Write the helper**

```python
# tests/helpers/range_server.py
"""Tiny HTTP server for transfer tests: Range support plus fault injection."""

from __future__ import annotations

import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FILE_SIZE = 5 * 1024 * 1024


class RangeServer:
    """Owns a background ThreadingHTTPServer serving one in-memory file."""

    def __init__(self) -> None:
        rng = random.Random(1234)
        self.data = bytes(rng.getrandbits(8) for _ in range(FILE_SIZE))
        self.etag = '"test-etag-1"'
        self.ignore_range = False
        self.no_ranges = False
        self.forbid_from_request: int | None = None
        self.abort_once_after: int | None = None
        self.get_count = 0
        self.in_flight = 0
        self.peak_in_flight = 0
        self._lock = threading.Lock()
        self._aborted_once = False
        server = self

        class Handler(BaseHTTPRequestHandler):  # pylint: disable=missing-class-docstring
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):  # silence
                return

            def _common_headers(self, length: int) -> None:
                self.send_header("Content-Length", str(length))
                self.send_header("ETag", server.etag)
                if not server.no_ranges:
                    self.send_header("Accept-Ranges", "bytes")

            def do_HEAD(self):  # pylint: disable=invalid-name
                self.send_response(200)
                self._common_headers(len(server.data))
                self.end_headers()

            def do_GET(self):  # pylint: disable=invalid-name
                with server._lock:  # pylint: disable=protected-access
                    server.get_count += 1
                    count = server.get_count
                    server.in_flight += 1
                    server.peak_in_flight = max(server.peak_in_flight, server.in_flight)
                try:
                    if server.forbid_from_request is not None and count >= server.forbid_from_request:
                        self.send_response(403)
                        self._common_headers(0)
                        self.end_headers()
                        return
                    rng_header = self.headers.get("Range")
                    start, end = 0, len(server.data) - 1
                    status = 200
                    if rng_header and not (server.ignore_range or server.no_ranges):
                        spec = rng_header.replace("bytes=", "")
                        lo, _, hi = spec.partition("-")
                        start = int(lo)
                        end = int(hi) if hi else end
                        if start >= len(server.data):
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{len(server.data)}")
                            self.end_headers()
                            return
                        status = 206
                    body = server.data[start:end + 1]
                    self.send_response(status)
                    self._common_headers(len(body))
                    if status == 206:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{len(server.data)}")
                    self.end_headers()
                    abort_at = None
                    with server._lock:  # pylint: disable=protected-access
                        if server.abort_once_after is not None and not server._aborted_once:  # pylint: disable=protected-access
                            server._aborted_once = True  # pylint: disable=protected-access
                            abort_at = server.abort_once_after
                    sent = 0
                    for offset in range(0, len(body), 65536):
                        chunk = body[offset:offset + 65536]
                        if abort_at is not None and sent + len(chunk) > abort_at:
                            self.wfile.write(chunk[: max(0, abort_at - sent)])
                            self.wfile.flush()
                            self.connection.close()
                            return
                        self.wfile.write(chunk)
                        sent += len(chunk)
                finally:
                    with server._lock:  # pylint: disable=protected-access
                        server.in_flight -= 1

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}/file.bin"

    def reset(self) -> None:
        """Clear counters and fault flags between scenarios."""
        self.ignore_range = False
        self.no_ranges = False
        self.forbid_from_request = None
        self.abort_once_after = None
        self.get_count = 0
        self.peak_in_flight = 0
        self._aborted_once = False

    def close(self) -> None:
        """Stop the server."""
        self._httpd.shutdown()
        self._httpd.server_close()
```

Add to `tests/conftest.py` (bottom):

```python
@pytest.fixture
def range_server():
    """Local HTTP server with Range support and fault injection (see tests/helpers)."""
    from tests.helpers.range_server import RangeServer  # pylint: disable=import-outside-toplevel

    server = RangeServer()
    try:
        yield server
    finally:
        server.close()
```

- [ ] **Step 2: Smoke-test the helper**

Run: `.venv/bin/python - <<'PY'
from tests.helpers.range_server import RangeServer
import requests
s = RangeServer()
h = requests.head(s.url); print(h.status_code, h.headers["Content-Length"], h.headers["Accept-Ranges"])
r = requests.get(s.url, headers={"Range": "bytes=10-19"}); print(r.status_code, r.headers["Content-Range"], r.content == s.data[10:20])
s.close()
PY`
Expected: `200 5242880 bytes` then `206 bytes 10-19/5242880 True`.

- [ ] **Step 3: Lint and commit**

Run: `.venv/bin/python -m pylint tests/helpers tests/conftest.py`
Expected: clean (the handler's `do_GET`/`do_HEAD` names carry the inline disables shown).

```bash
git add tests/helpers/__init__.py tests/helpers/range_server.py tests/conftest.py
git commit -m "test: range-capable HTTP server fixture with fault injection"
```

---

### Task 6: `plan_transfer` (pure decision) and `SegmentedOutcome`

**Files:**
- Create: `src/downloaders/segmented_download.py` (first half)
- Test: `tests/unit/test_segmented_download.py` (first tests)

**Interfaces:**
- Consumes: `RemoteInfo` (Task 3), `TransferSettings` (Task 1), `TransferManifest` (Task 2).
- Produces:
  ```python
  class TransferMode(Enum): SINGLE_NO_RESUME; SINGLE; SEGMENTED
  class SegmentedOutcome(Enum): COMPLETE; RETRYABLE; NEEDS_REFRESH; RANGE_UNSUPPORTED; MANIFEST_INVALID; TERMINAL; CANCELLED
  @dataclass(frozen=True) class TransferPlan: mode: TransferMode; manifest: TransferManifest | None; remote: RemoteInfo
  def plan_transfer(remote, settings, *, existing: TransferManifest | None, url_origin: str | None) -> TransferPlan
  MANIFEST_FLUSH_BYTES = 8 * 1024 * 1024
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_segmented_download.py
"""plan_transfer decisions and the SegmentedDownloader against a local range server."""

# pylint: disable=missing-function-docstring,too-many-arguments
from __future__ import annotations

from src.config import TransferSettings
from src.downloaders.remote_probe import RemoteInfo
from src.downloaders.segmented_download import TransferMode, plan_transfer
from src.downloaders.transfer_manifest import TransferManifest

SETTINGS = TransferSettings(segments=4, segment_min_bytes=32 * 1024 * 1024,
                            max_connections=12, partial_max_age_hours=168)


def test_plan_unknown_size_is_single_no_resume():
    plan = plan_transfer(RemoteInfo(None, None, False), SETTINGS, existing=None, url_origin=None)
    assert plan.mode is TransferMode.SINGLE_NO_RESUME and plan.manifest is None


def test_plan_no_range_support_is_single_no_resume():
    plan = plan_transfer(RemoteInfo(10**9, '"e"', False), SETTINGS, existing=None, url_origin=None)
    assert plan.mode is TransferMode.SINGLE_NO_RESUME


def test_plan_small_file_is_single_resumable_with_one_segment():
    plan = plan_transfer(RemoteInfo(10 * 1024 * 1024, '"e"', True), SETTINGS, existing=None, url_origin="o")
    assert plan.mode is TransferMode.SINGLE
    assert plan.manifest is not None and len(plan.manifest.segments) == 1
    assert plan.manifest.url_origin == "o"


def test_plan_segments_one_is_single_resumable():
    s = TransferSettings(segments=1, segment_min_bytes=1, max_connections=12, partial_max_age_hours=0)
    plan = plan_transfer(RemoteInfo(10**9, None, True), s, existing=None, url_origin=None)
    assert plan.mode is TransferMode.SINGLE and len(plan.manifest.segments) == 1


def test_plan_segmented_count_limited_by_min_segment_size():
    # 100 MB / 32 MB min -> at most 3 segments even though 4 requested
    plan = plan_transfer(RemoteInfo(100 * 1024 * 1024, '"e"', True), SETTINGS, existing=None, url_origin=None)
    assert plan.mode is TransferMode.SEGMENTED and len(plan.manifest.segments) == 3


def test_plan_reuses_existing_manifest():
    existing = TransferManifest.plan(10**9, 4, etag='"e"')
    existing.segments[0].done = 5
    plan = plan_transfer(RemoteInfo(10**9, '"e"', True), SETTINGS, existing=existing, url_origin=None)
    assert plan.manifest is existing and plan.mode is TransferMode.SEGMENTED


def test_plan_existing_single_segment_manifest_stays_single():
    existing = TransferManifest.plan(10**9, 1, etag=None)
    plan = plan_transfer(RemoteInfo(10**9, None, True), SETTINGS, existing=existing, url_origin=None)
    assert plan.mode is TransferMode.SINGLE and plan.manifest is existing
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_segmented_download.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the planning half of the module**

```python
# src/downloaders/segmented_download.py
"""Parallel byte-range transfer into one pre-sized file, resumable via a manifest.

See docs/superpowers/specs/2026-10-21-segmented-resumable-downloads-design.md.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

import requests
from requests.exceptions import ChunkedEncodingError, RequestException

from src.config import HTTPStatus, TransferSettings
from src.managers.progress_manager import ProgressManager

from .connection_governor import GOVERNOR, Cancelled, ConnectionGovernor
from .download_utils import get_chunk_size
from .remote_probe import RemoteInfo
from .transfer_manifest import (
    Segment,
    TransferManifest,
    manifest_path,
    save_manifest,
)

MANIFEST_FLUSH_BYTES = 8 * 1024 * 1024


class TransferMode(Enum):
    """How a file will be fetched."""

    SINGLE_NO_RESUME = "single_no_resume"   # unknown size or no Range support
    SINGLE = "single"                       # one stream, manifest-backed resume
    SEGMENTED = "segmented"                 # N range workers


class SegmentedOutcome(Enum):
    """Result of one :meth:`SegmentedDownloader.run`."""

    COMPLETE = "complete"
    RETRYABLE = "retryable"
    NEEDS_REFRESH = "needs_refresh"          # 401/403: signed URL expired
    RANGE_UNSUPPORTED = "range_unsupported"  # server answered 200 to a Range GET
    MANIFEST_INVALID = "manifest_invalid"    # 416 / Content-Range mismatch
    TERMINAL = "terminal"                    # disk error
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TransferPlan:
    """Decision produced by :func:`plan_transfer`."""

    mode: TransferMode
    manifest: TransferManifest | None
    remote: RemoteInfo


def plan_transfer(
    remote: RemoteInfo,
    settings: TransferSettings,
    *,
    existing: TransferManifest | None,
    url_origin: str | None,
) -> TransferPlan:
    """Choose single vs segmented and build (or adopt) the manifest.

    ``existing`` must already have been validated against ``remote`` by the
    caller (see ``manifest_matches_remote``); it is adopted as-is so its
    segment layout and progress survive.
    """
    if remote.size is None or not remote.accepts_ranges:
        return TransferPlan(TransferMode.SINGLE_NO_RESUME, None, remote)

    if existing is not None:
        mode = TransferMode.SEGMENTED if len(existing.segments) > 1 else TransferMode.SINGLE
        return TransferPlan(mode, existing, remote)

    if settings.segments <= 1 or remote.size < settings.segment_min_bytes:
        manifest = TransferManifest.plan(remote.size, 1, etag=remote.etag, url_origin=url_origin)
        return TransferPlan(TransferMode.SINGLE, manifest, remote)

    by_min_size = max(1, math.floor(remote.size / settings.segment_min_bytes))
    count = min(settings.segments, by_min_size)
    manifest = TransferManifest.plan(remote.size, count, etag=remote.etag, url_origin=url_origin)
    mode = TransferMode.SEGMENTED if count > 1 else TransferMode.SINGLE
    return TransferPlan(mode, manifest, remote)
```

(The remaining imports — `logging`, `os`, `threading`, `ThreadPoolExecutor`, `Callable`, `requests`, `ChunkedEncodingError`, `RequestException`, `HTTPStatus`, `ProgressManager`, `GOVERNOR`, `Cancelled`, `ConnectionGovernor`, `get_chunk_size`, `Segment`, `manifest_path`, `save_manifest` — are used by Task 7; pylint will flag them as unused until then, so **run pylint on this file only after Task 7**, or add the `SegmentedDownloader` skeleton in the same commit. Simplest: do Task 6 and Task 7 as two commits but run the full pylint gate at the end of Task 7.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_segmented_download.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/segmented_download.py tests/unit/test_segmented_download.py
git commit -m "feat(download): transfer planning (single vs segmented)"
```

---

### Task 7: `SegmentedDownloader`

**Files:**
- Modify: `src/downloaders/segmented_download.py` (append)
- Test: `tests/unit/test_segmented_download.py` (append)

**Interfaces:**
- Consumes: `range_server` fixture (Task 5), governor (Task 4), manifest (Task 2).
- Produces:
  ```python
  class SegmentedDownloader:
      def __init__(self, *, url: str, headers: dict[str, str], temp_path: Path, manifest: TransferManifest,
                   progress_manager: ProgressManager, task: int, governor: ConnectionGovernor = GOVERNOR,
                   cancel_event: threading.Event | None = None, timeout: float = 30.0,
                   flush_bytes: int = MANIFEST_FLUSH_BYTES) -> None
      def run(self) -> SegmentedOutcome
  ```
  Side effects: pre-sizes `temp_path` to `manifest.size`, writes manifest to `manifest_path(temp_path)` on every flush and on exit, calls `progress_manager.update_task(task, completed=<pct>)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_segmented_download.py`)

```python
import hashlib
import threading
from pathlib import Path

from src.downloaders.connection_governor import ConnectionGovernor
from src.downloaders.segmented_download import SegmentedDownloader, SegmentedOutcome
from src.downloaders.transfer_manifest import load_manifest, manifest_path


class _PM:  # minimal progress manager
    def __init__(self):
        self.completed: list[float] = []
        self.logs: list[str] = []

    def update_task(self, _task, completed=None, advance=0, visible=True):  # pylint: disable=unused-argument
        if completed is not None:
            self.completed.append(completed)

    def update_log(self, *, event, details):  # pylint: disable=unused-argument
        self.logs.append(details)


def _run(server, tmp_path, manifest=None, segments=4, **kwargs):
    temp = tmp_path / "file.bin.temp"
    manifest = manifest or TransferManifest.plan(len(server.data), segments, etag=server.etag)
    pm = _PM()
    dl = SegmentedDownloader(url=server.url, headers={}, temp_path=temp, manifest=manifest,
                             progress_manager=pm, task=0, flush_bytes=256 * 1024, **kwargs)
    return dl.run(), temp, manifest, pm


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_segmented_full_transfer_matches_source(range_server, tmp_path):
    outcome, temp, manifest, pm = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.COMPLETE
    assert manifest.complete and temp.stat().st_size == len(range_server.data)
    assert _sha(temp) == hashlib.sha256(range_server.data).hexdigest()
    assert pm.completed and pm.completed[-1] == 100.0
    assert range_server.get_count == 4


def test_segmented_resumes_from_manifest(range_server, tmp_path):
    manifest = TransferManifest.plan(len(range_server.data), 4, etag=range_server.etag)
    temp = tmp_path / "file.bin.temp"
    # Pretend segment 0 is fully on disk and segment 1 half done; write those bytes ourselves.
    with temp.open("wb") as fh:
        fh.truncate(len(range_server.data))
        s0, s1 = manifest.segments[0], manifest.segments[1]
        fh.seek(s0.start); fh.write(range_server.data[s0.start:s0.end + 1]); s0.done = s0.length
        half = s1.length // 2
        fh.seek(s1.start); fh.write(range_server.data[s1.start:s1.start + half]); s1.done = half
    outcome, temp, manifest, _ = _run(range_server, tmp_path, manifest=manifest)
    assert outcome is SegmentedOutcome.COMPLETE
    assert _sha(temp) == hashlib.sha256(range_server.data).hexdigest()
    assert range_server.get_count == 3     # segment 0 never re-fetched


def test_segmented_falls_back_when_server_ignores_range(range_server, tmp_path):
    range_server.ignore_range = True
    outcome, _, manifest, _ = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.RANGE_UNSUPPORTED
    assert manifest.bytes_done == 0      # nothing trusted from a 200 body


def test_segmented_403_requests_link_refresh_and_keeps_progress(range_server, tmp_path):
    range_server.forbid_from_request = 3        # first two segment GETs succeed, rest 403
    outcome, temp, manifest, _ = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.NEEDS_REFRESH
    saved = load_manifest(manifest_path(temp))
    assert saved is not None and saved.bytes_done == manifest.bytes_done > 0
    # second run with a "fresh" URL completes from where it left off
    range_server.forbid_from_request = None
    range_server.get_count = 0
    outcome2, temp, manifest, _ = _run(range_server, tmp_path, manifest=saved)
    assert outcome2 is SegmentedOutcome.COMPLETE and _sha(temp) == hashlib.sha256(range_server.data).hexdigest()


def test_segmented_mid_stream_abort_is_retryable_and_resumable(range_server, tmp_path):
    range_server.abort_once_after = 100_000
    outcome, temp, manifest, _ = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.RETRYABLE
    saved = load_manifest(manifest_path(temp))
    assert saved is not None and 0 < saved.bytes_done < len(range_server.data)
    outcome2, temp, _, _ = _run(range_server, tmp_path, manifest=saved)
    assert outcome2 is SegmentedOutcome.COMPLETE and _sha(temp) == hashlib.sha256(range_server.data).hexdigest()


def test_segmented_cancel_leaves_resumable_manifest(range_server, tmp_path):
    cancel = threading.Event()
    cancel.set()                                   # cancelled before the first chunk
    outcome, temp, _, _ = _run(range_server, tmp_path, cancel_event=cancel)
    assert outcome is SegmentedOutcome.CANCELLED
    saved = load_manifest(manifest_path(temp))
    assert saved is not None and saved.bytes_done == 0 and temp.stat().st_size == len(range_server.data)


def test_segmented_respects_governor_cap(range_server, tmp_path):
    gov = ConnectionGovernor(2)
    outcome, _, _, _ = _run(range_server, tmp_path, governor=gov)
    assert outcome is SegmentedOutcome.COMPLETE
    assert range_server.peak_in_flight <= 2


def test_segmented_disk_error_is_terminal_and_keeps_manifest(range_server, tmp_path, monkeypatch):
    import src.downloaders.segmented_download as mod  # pylint: disable=import-outside-toplevel

    def boom(*_a, **_k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(mod.os, "pwrite", boom)
    outcome, temp, _, _ = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.TERMINAL
    assert manifest_path(temp).exists()


def test_segmented_416_marks_manifest_invalid(range_server, tmp_path):
    # Manifest claims the file is 10 MB larger than the server's object: the
    # second segment starts past EOF (server answers 416) and the first gets a
    # Content-Range that disagrees with what it asked for. Both are manifest
    # errors, never silently accepted.
    manifest = TransferManifest.plan(len(range_server.data) + 10_000_000, 2, etag=range_server.etag)
    outcome, _, _, _ = _run(range_server, tmp_path, manifest=manifest)
    assert outcome is SegmentedOutcome.MANIFEST_INVALID
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_segmented_download.py -q -k segmented`
Expected: FAIL — `ImportError: cannot import name 'SegmentedDownloader'`.

- [ ] **Step 3: Append the downloader to `src/downloaders/segmented_download.py`**

```python
class _LinkExpired(Exception):
    """401/403 from the CDN: the signed URL is no longer valid."""


class _RangeUnsupported(Exception):
    """Server answered 200 to a Range request."""


class _ManifestInvalid(Exception):
    """416 or Content-Range disagreement: local offsets are wrong."""


class SegmentedDownloader:  # pylint: disable=too-many-instance-attributes
    """Fetch every incomplete segment of ``manifest`` in parallel into ``temp_path``."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        url: str,
        headers: dict[str, str],
        temp_path: Path,
        manifest: TransferManifest,
        progress_manager: ProgressManager,
        task: int,
        governor: ConnectionGovernor = GOVERNOR,
        cancel_event: threading.Event | None = None,
        timeout: float = 30.0,
        flush_bytes: int = MANIFEST_FLUSH_BYTES,
    ) -> None:
        self.url = url
        self.headers = headers
        self.temp_path = temp_path
        self.manifest = manifest
        self.progress_manager = progress_manager
        self.task = task
        self.governor = governor
        self.cancel_event = cancel_event or threading.Event()
        self.timeout = timeout
        self.flush_bytes = flush_bytes
        self._lock = threading.Lock()
        self._total = manifest.bytes_done
        self._fd: int | None = None

    # ---- public -----------------------------------------------------------

    def run(self) -> SegmentedOutcome:
        """Run all incomplete segments; always leaves a consistent manifest on disk."""
        try:
            self._prepare_file()
        except OSError as os_err:
            logging.warning("Cannot prepare %s: %s", self.temp_path, os_err)
            return SegmentedOutcome.TERMINAL

        pending = [s for s in self.manifest.segments if not s.complete]
        if not pending:
            self._flush()
            return SegmentedOutcome.COMPLETE

        outcome = SegmentedOutcome.COMPLETE
        try:
            with ThreadPoolExecutor(max_workers=len(pending)) as pool:
                futures = [pool.submit(self._fetch_segment, seg) for seg in pending]
                for future in futures:
                    try:
                        future.result()
                    except Cancelled:
                        outcome = _worst(outcome, SegmentedOutcome.CANCELLED)
                        self.cancel_event.set()
                    except _LinkExpired:
                        outcome = _worst(outcome, SegmentedOutcome.NEEDS_REFRESH)
                        self.cancel_event.set()
                    except _RangeUnsupported:
                        outcome = _worst(outcome, SegmentedOutcome.RANGE_UNSUPPORTED)
                        self.cancel_event.set()
                    except _ManifestInvalid:
                        outcome = _worst(outcome, SegmentedOutcome.MANIFEST_INVALID)
                        self.cancel_event.set()
                    except OSError:
                        outcome = _worst(outcome, SegmentedOutcome.TERMINAL)
                        self.cancel_event.set()
                    except (RequestException, ChunkedEncodingError):
                        outcome = _worst(outcome, SegmentedOutcome.RETRYABLE)
        finally:
            self._flush()
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

        if outcome is SegmentedOutcome.COMPLETE and not self.manifest.complete:
            return SegmentedOutcome.RETRYABLE
        if outcome is SegmentedOutcome.RANGE_UNSUPPORTED:
            for seg in self.manifest.segments:
                seg.done = 0
            self._flush()
        return outcome

    # ---- internals ----------------------------------------------------------

    def _prepare_file(self) -> None:
        flags = os.O_RDWR | os.O_CREAT
        self._fd = os.open(self.temp_path, flags, 0o644)
        if os.fstat(self._fd).st_size != self.manifest.size:
            os.ftruncate(self._fd, self.manifest.size)

    def _flush(self) -> None:
        with self._lock:
            save_manifest(self.manifest, manifest_path(self.temp_path))

    def _report(self, delta: int) -> None:
        with self._lock:
            self._total += delta
            pct = min(100.0, (self._total / self.manifest.size) * 100) if self.manifest.size else 0.0
        self.progress_manager.update_task(self.task, completed=pct)

    def _fetch_segment(self, segment: Segment) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()
        headers = dict(self.headers)
        headers["Range"] = f"bytes={segment.next_offset}-{segment.end}"
        with self.governor.slot(cancel_event=self.cancel_event):
            with requests.get(self.url, headers=headers, stream=True, timeout=self.timeout) as resp:
                self._check_response(resp, segment)
                chunk_size = get_chunk_size(segment.length)
                since_flush = 0
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if self.cancel_event.is_set():
                        raise Cancelled()
                    if not chunk:
                        continue
                    chunk = chunk[: segment.remaining]
                    assert self._fd is not None
                    written = os.pwrite(self._fd, chunk, segment.next_offset)
                    segment.done += written
                    since_flush += written
                    self._report(written)
                    if since_flush >= self.flush_bytes:
                        self._flush()
                        since_flush = 0
                    if segment.complete:
                        break
        self._flush()

    def _check_response(self, resp: requests.Response, segment: Segment) -> None:
        if resp.status_code in (HTTPStatus.FORBIDDEN, 401):
            raise _LinkExpired()
        if resp.status_code == 416:
            raise _ManifestInvalid()
        if resp.status_code == HTTPStatus.OK:
            raise _RangeUnsupported()
        resp.raise_for_status()
        if resp.status_code != 206:
            raise _ManifestInvalid()
        content_range = resp.headers.get("Content-Range", "")
        expected = f"bytes {segment.next_offset}-{segment.end}/{self.manifest.size}"
        if content_range.replace(" ", "") != expected.replace(" ", ""):
            raise _ManifestInvalid()


_SEVERITY = {
    SegmentedOutcome.COMPLETE: 0,
    SegmentedOutcome.RETRYABLE: 1,
    SegmentedOutcome.NEEDS_REFRESH: 2,
    SegmentedOutcome.CANCELLED: 3,
    SegmentedOutcome.RANGE_UNSUPPORTED: 4,
    SegmentedOutcome.MANIFEST_INVALID: 5,
    SegmentedOutcome.TERMINAL: 6,
}


def _worst(current: SegmentedOutcome, new: SegmentedOutcome) -> SegmentedOutcome:
    """Keep the more severe of two outcomes."""
    return new if _SEVERITY[new] > _SEVERITY[current] else current
```

Note the test for 416 sets `done` beyond the segment length; `_fetch_segment` must therefore send the Range before checking `segment.remaining` — which it does (`next_offset` is start+done). The 403 test relies on segment workers starting in order; `ThreadPoolExecutor` submits in list order and the server counts GETs as they arrive, so with `forbid_from_request = 3` at least the first two succeed. If this proves flaky on a loaded CI runner, raise `forbid_from_request` to 4 and assert `bytes_done > 0` only.

- [ ] **Step 4: Run tests and the lint gate**

Run: `.venv/bin/python -m pytest tests/unit/test_segmented_download.py -q && .venv/bin/python -m pylint src/downloaders/segmented_download.py tests/unit/test_segmented_download.py tests/helpers`
Expected: all pass; pylint 10.00. If pylint flags `too-many-branches` on `run`, split the `except` ladder into a helper `_classify(exc) -> SegmentedOutcome` and keep behaviour identical.

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/segmented_download.py tests/unit/test_segmented_download.py
git commit -m "feat(download): SegmentedDownloader with manifest-backed resume"
```

---

### Task 8: Single-stream resume in `download_utils`

**Files:**
- Modify: `src/downloaders/download_utils.py:174-217` (`_finalise_download`) and `:220-320` (`save_file_with_progress`)
- Test: `tests/unit/test_download_utils.py` (append)

**Interfaces:**
- Consumes: `TransferManifest`, `manifest_path`, `save_manifest` (Task 2).
- Produces (new keyword params, all optional so existing callers are unchanged):
  ```python
  def save_file_with_progress(response, download_path, task, progress_manager, *,
                              download_url=None, download_headers=None,
                              resume_from: int = 0, manifest: TransferManifest | None = None) -> DownloadOutcome
  def _finalise_download(*, file_size, total_downloaded, temp_path, final_path, progress_manager, task,
                         manifest_file: Path | None = None) -> DownloadOutcome
  ```
  Behaviour: with `resume_from > 0` the temp file is opened `r+b`, seeked to `resume_from`, and `total_downloaded` starts there; when `manifest` is given its single segment's `done` tracks `total_downloaded` and is saved every `MANIFEST_FLUSH_BYTES` and on exit; on SUCCESS the manifest file is deleted.

- [ ] **Step 1: Write the failing tests** (append; reuse the file's existing `FakeResponse` and `_FakeRaw` helpers, which take `chunks` and a `headers` dict)

```python
def test_save_file_resumes_from_offset_and_updates_manifest(tmp_path, fake_live_manager):
    from src.downloaders.transfer_manifest import TransferManifest, load_manifest, manifest_path  # pylint: disable=import-outside-toplevel

    final = tmp_path / "f.bin"
    temp = final.with_suffix(".temp")
    temp.write_bytes(b"A" * 10 + b"\0" * 10)           # 10 good bytes, pre-sized to 20
    manifest = TransferManifest.plan(20, 1, etag=None)
    manifest.segments[0].done = 10
    response = FakeResponse(chunks=[b"B" * 5, b"B" * 5], headers={"Content-Length": "10"})
    outcome = save_file_with_progress(
        response, str(final), 0, fake_live_manager,
        resume_from=10, manifest=manifest,
    )
    assert outcome is DownloadOutcome.SUCCESS
    assert final.read_bytes() == b"A" * 10 + b"B" * 10
    assert not manifest_path(temp).exists()            # removed on success


def test_save_file_partial_keeps_manifest_progress(tmp_path, fake_live_manager):
    from src.downloaders.transfer_manifest import TransferManifest, load_manifest, manifest_path  # pylint: disable=import-outside-toplevel

    final = tmp_path / "g.bin"
    temp = final.with_suffix(".temp")
    manifest = TransferManifest.plan(30, 1, etag='"e"')
    response = FakeResponse(chunks=[b"x" * 10, ChunkedEncodingError("cut")], headers={"Content-Length": "30"})
    outcome = save_file_with_progress(response, str(final), 0, fake_live_manager, manifest=manifest)
    assert outcome is DownloadOutcome.RETRYABLE_FAILURE
    saved = load_manifest(manifest_path(temp))
    assert saved is not None and saved.segments[0].done == 10
    assert temp.exists()
```

If `FakeResponse` in the file does not already support an exception instance inside `chunks` (raise when reached), extend its `iter_content` with:

```python
            for chunk in self._chunks:
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_download_utils.py -q -k "resumes or partial_keeps"`
Expected: FAIL — `TypeError: save_file_with_progress() got an unexpected keyword argument 'resume_from'`.

- [ ] **Step 3: Implement**

In `_finalise_download` add the parameter and delete the manifest after a successful move, in **both** branches:

```python
def _finalise_download(  # pylint: disable=too-many-arguments
    *,
    file_size: int | None,
    total_downloaded: int,
    temp_path: Path,
    final_path: str,
    progress_manager: ProgressManager,
    task: int,
    manifest_file: Path | None = None,
) -> DownloadOutcome:
    ...  # existing body, but replace each `shutil.move(temp_path, final_path)` success path with:
        try:
            shutil.move(temp_path, final_path)
        except OSError as os_err:
            _log_once(progress_manager, f"Could not finalise {final_path}: {os_err}")
            progress_manager.update_task(task, completed=0, visible=False)
            return DownloadOutcome.RETRYABLE_FAILURE
        _remove_quietly(manifest_file)
        progress_manager.update_task(task, completed=100)
        return DownloadOutcome.SUCCESS
```

Add near `_log_once`:

```python
def _remove_quietly(path: Path | None) -> None:
    """Delete ``path`` if given; a missing file is fine."""
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
```

In `save_file_with_progress`:

```python
def save_file_with_progress(  # pylint: disable=too-many-locals,too-many-arguments,too-many-branches,too-many-statements
    response: Response,
    download_path: str,
    task: int,
    progress_manager: ProgressManager,
    *,
    download_url: str | None = None,
    download_headers: dict[str, str] | None = None,
    resume_from: int = 0,
    manifest: TransferManifest | None = None,
) -> DownloadOutcome:
    """...existing docstring, plus:

    ``resume_from`` > 0 means the caller issued a Range GET and the first
    ``resume_from`` bytes are already in the ``.temp`` file; writing continues
    at that offset. ``manifest`` (single-segment) is kept in step with the
    byte count so an interrupted stream can resume on the next attempt.
    """
    file_size, head_future, head_executor = _resolve_content_length(
        response, download_url, headers=download_headers,
    )
    if file_size is not None and resume_from:
        file_size += resume_from          # Content-Length of a 206 is the remainder
    if manifest is not None:
        file_size = manifest.size
    ...
    temp_download_path = Path(download_path).with_suffix(".temp")
    manifest_file = manifest_path(temp_download_path) if manifest is not None else None
    chunk_size = get_chunk_size(file_size or 0)
    total_downloaded = resume_from
    since_flush = 0
    ...
    try:
        mode = "r+b" if resume_from else "wb"
        with temp_download_path.open(mode) as file:
            if resume_from:
                file.seek(resume_from)
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk is not None:
                    file.write(chunk)
                    total_downloaded += len(chunk)
                    since_flush += len(chunk)
                    if manifest is not None:
                        manifest.segments[0].done = total_downloaded
                        if since_flush >= MANIFEST_FLUSH_BYTES:
                            save_manifest(manifest, manifest_file)
                            since_flush = 0
                    ... # existing progress / head_future logic unchanged
    except ChunkedEncodingError:
        if manifest is not None:
            save_manifest(manifest, manifest_file)
        ... # existing log + hide + return RETRYABLE_FAILURE
    finally:
        ...
    if manifest is not None:
        save_manifest(manifest, manifest_file)
    return _finalise_download(
        ..., manifest_file=manifest_file,
    )
```

Imports to add at the top of `download_utils.py`:

```python
from .transfer_manifest import TransferManifest, manifest_path, save_manifest
MANIFEST_FLUSH_BYTES = 8 * 1024 * 1024
```

and in `segmented_download.py` change `MANIFEST_FLUSH_BYTES = 8 * 1024 * 1024` to `from .download_utils import MANIFEST_FLUSH_BYTES, get_chunk_size` so there is one definition.

- [ ] **Step 4: Run the download tests and lint**

Run: `.venv/bin/python -m pytest tests/unit/test_download_utils.py tests/unit/test_segmented_download.py -q && .venv/bin/python -m pylint src/downloaders`
Expected: all pass (existing tests untouched in behaviour); pylint clean.

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/download_utils.py src/downloaders/segmented_download.py tests/unit/test_download_utils.py
git commit -m "feat(download): single-stream resume with manifest upkeep"
```

---

### Task 9: `MediaDownloader` orchestration and link refresh

**Files:**
- Modify: `src/downloaders/media_downloader.py:59-101` (`attempt_download`) plus new private helpers
- Modify: `src/config.py` — add `HTTPStatus.UNAUTHORIZED = 401` and `HTTPStatus.PARTIAL_CONTENT = 206`, `HTTPStatus.RANGE_NOT_SATISFIABLE = 416`
- Test: `tests/unit/test_media_downloader_transfer.py`

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: no new public API. `attempt_download(final_path) -> DownloadOutcome` now:
  1. `settings = resolve_transfer_settings(self.session_info.args)`; `GOVERNOR.raise_limit(max(settings.max_connections, max_workers))` where `max_workers = getattr(args, "max_workers", MAX_WORKERS)`.
  2. `remote = probe_remote(link, download_headers)`.
  3. `existing = load_manifest(manifest_path(temp))`; if present and `not manifest_matches_remote(existing, size=remote.size, etag=remote.etag)` → `discard_partial(temp)`, log `"Discarding stale partial for <name>: remote file changed"`, `existing=None`.
  4. `plan = plan_transfer(remote, settings, existing=existing, url_origin=item_page)`; if `existing` and `existing.bytes_done` → log `"Resuming <name>: NN% already on disk"`.
  5. `SEGMENTED` → `_run_segmented(plan, ...)`; else `_run_single(plan, ...)`.
  - `_run_segmented` loop (bounded by `self.retries`): `COMPLETE` → `_finalise_download(size, size, temp, final, pm, task, manifest_file)`; `NEEDS_REFRESH` → `self._refresh_link()`; if it returns a new link set `self.download_info.download_link` and continue, else return `RETRYABLE_FAILURE`; `RANGE_UNSUPPORTED` → `discard_partial`, fall through to `_run_single` with `TransferMode.SINGLE_NO_RESUME`; `MANIFEST_INVALID` → `discard_partial` once and re-plan, second time `TERMINAL_FAILURE`; `RETRYABLE` → `self._retry_with_backoff(attempt, event="Retrying download")` and continue or `RETRYABLE_FAILURE`; `TERMINAL` → `TERMINAL_FAILURE`; `CANCELLED` → `RETRYABLE_FAILURE`.
  - `_run_single`: today's `requests.get` loop, but when `plan.manifest` exists with `done > 0` add `Range: bytes=<done>-`; a `206` → `save_file_with_progress(..., resume_from=done, manifest=plan.manifest)`; a `200` with `done > 0` → `discard_partial`, re-plan fresh single, call without resume; a `416` → `discard_partial` and retry fresh once; `403` with `item_page` → `_refresh_link()` then retry.
  - `_refresh_link() -> str | None`: if `self.download_info.item_page` is `None` → `None`; else fetch the page with `requests.get(item_page, headers=network.headers, timeout=20)`, parse with BeautifulSoup, `asyncio.run(get_download_info(item_page, soup, network=network))`, log `"Signed URL expired; re-resolved <name>"`, return the link.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_media_downloader_transfer.py
"""MediaDownloader: probe → manifest validation → plan → run, and link refresh."""

# pylint: disable=missing-function-docstring,protected-access
from __future__ import annotations

import hashlib
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from src.config import DownloadInfo, NetworkContext, SessionInfo
from src.downloaders.download_utils import DownloadOutcome
from src.downloaders.media_downloader import MediaDownloader
from src.downloaders.transfer_manifest import TransferManifest, manifest_path, save_manifest


def _dl(fake_live_manager, tmp_path, url, *, segments=4, min_mb=1, item_page=None):
    args = Namespace(skip_status_check=True, status_cache_ttl=60, maintenance_strategy="skip",
                     segments=segments, segment_min_size_mb=min_mb, max_connections=12,
                     partial_max_age_hours=0, max_workers=1)
    network = NetworkContext(status_page="https://s.example/", bunkr_api="https://a.example/",
                             fallback_domain="example.cr", user_agent="t/1", download_referer="https://r.example/")
    si = SessionInfo(args=args, bunkr_status={}, download_path=str(tmp_path), network=network)
    return MediaDownloader(session_info=si,
                           download_info=DownloadInfo(download_link=url, filename="file.bin", task=0, item_page=item_page),
                           live_manager=fake_live_manager, retries=3)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_attempt_download_segmented_end_to_end(range_server, tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    final = tmp_path / "file.bin"
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert _sha(final.read_bytes()) == _sha(range_server.data)
    assert not manifest_path(final.with_suffix(".temp")).exists()
    assert range_server.get_count == 4


def test_attempt_download_single_stream_below_threshold(range_server, tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, range_server.url, min_mb=100)   # 5 MB file < 100 MB
    final = tmp_path / "file.bin"
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert range_server.get_count == 1 and _sha(final.read_bytes()) == _sha(range_server.data)


def test_attempt_download_resumes_existing_manifest_and_logs(range_server, tmp_path, fake_live_manager):
    final = tmp_path / "file.bin"
    temp = final.with_suffix(".temp")
    manifest = TransferManifest.plan(len(range_server.data), 4, etag=range_server.etag)
    s0 = manifest.segments[0]
    with temp.open("wb") as fh:
        fh.truncate(len(range_server.data)); fh.seek(0); fh.write(range_server.data[: s0.length])
    s0.done = s0.length
    save_manifest(manifest, manifest_path(temp))
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert range_server.get_count == 3
    assert any("Resuming" in d for _, d in fake_live_manager.logs)


def test_attempt_download_discards_mismatched_manifest(range_server, tmp_path, fake_live_manager):
    final = tmp_path / "file.bin"
    temp = final.with_suffix(".temp")
    stale = TransferManifest.plan(len(range_server.data) + 1, 4, etag='"old"')
    stale.segments[0].done = 1000
    temp.write_bytes(b"\0" * 1000)
    save_manifest(stale, manifest_path(temp))
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert _sha(final.read_bytes()) == _sha(range_server.data)
    assert any("stale partial" in d for _, d in fake_live_manager.logs)


def test_attempt_download_refreshes_expired_link(range_server, tmp_path, fake_live_manager):
    range_server.forbid_from_request = 3
    dl = _dl(fake_live_manager, tmp_path, range_server.url, item_page="https://bunkr.cr/f/abc")

    def fake_refresh():
        range_server.forbid_from_request = None
        return range_server.url + "?token=fresh"
    with patch.object(dl, "_refresh_link", side_effect=fake_refresh) as refresh:
        assert dl.attempt_download(str(tmp_path / "file.bin")) is DownloadOutcome.SUCCESS
    refresh.assert_called_once()
    assert dl.download_info.download_link.endswith("?token=fresh")


def test_attempt_download_range_unsupported_falls_back(range_server, tmp_path, fake_live_manager):
    range_server.ignore_range = True
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    final = tmp_path / "file.bin"
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert _sha(final.read_bytes()) == _sha(range_server.data)


def test_refresh_link_without_item_page_is_none(range_server, tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    assert dl._refresh_link() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_media_downloader_transfer.py -q`
Expected: FAIL (segmented test: `get_count == 1`, no `_refresh_link` attribute, etc.).

- [ ] **Step 3: Implement**

Add to `HTTPStatus` in `src/config.py`:

```python
    PARTIAL_CONTENT = 206
    UNAUTHORIZED = 401
    RANGE_NOT_SATISFIABLE = 416
```

Replace `attempt_download` in `media_downloader.py` and add helpers (new imports: `asyncio`, `from bs4 import BeautifulSoup`, `from src.config import MAX_WORKERS, resolve_transfer_settings, TransferMode?` — no: `TransferMode` lives in `segmented_download`; import `from src.crawlers.crawler_utils import get_download_info`, `from .connection_governor import GOVERNOR`, `from .remote_probe import probe_remote`, `from .segmented_download import SegmentedDownloader, SegmentedOutcome, TransferMode, TransferPlan, plan_transfer`, `from .transfer_manifest import discard_partial, load_manifest, manifest_matches_remote, manifest_path`, and `from .download_utils import DownloadOutcome, _finalise_download, save_file_with_progress` — rename `_finalise_download` to public `finalise_download` in `download_utils.py` (keep a `_finalise_download = finalise_download` alias for the existing tests)):

```python
    def attempt_download(self, final_path: str) -> DownloadOutcome:
        """Download ``final_path`` with retries, segmentation and resume (spec §Architecture)."""
        headers = self._download_headers()
        settings = resolve_transfer_settings(self.session_info.args)
        max_workers = getattr(self.session_info.args, "max_workers", MAX_WORKERS) or MAX_WORKERS
        GOVERNOR.raise_limit(max(settings.max_connections, max_workers))

        temp_path = Path(final_path).with_suffix(".temp")
        remote = probe_remote(self.download_info.download_link, headers)
        existing = load_manifest(manifest_path(temp_path))
        if existing is not None and not manifest_matches_remote(
            existing, size=remote.size, etag=remote.etag,
        ):
            discard_partial(temp_path)
            self.live_manager.update_log(
                event="Download progress",
                details=f"Discarding stale partial for {self.download_info.filename}: remote file changed.",
            )
            existing = None
        plan = plan_transfer(remote, settings, existing=existing, url_origin=self.download_info.item_page)
        if existing is not None and existing.bytes_done:
            pct = existing.bytes_done * 100 // max(existing.size, 1)
            self.live_manager.update_log(
                event="Download progress",
                details=f"Resuming {self.download_info.filename}: {pct}% already on disk.",
            )
        if plan.mode is TransferMode.SEGMENTED:
            return self._run_segmented(plan, temp_path, final_path, headers)
        return self._run_single(plan, temp_path, final_path, headers)

    def _download_headers(self) -> dict[str, str]:
        return (
            self.session_info.network.download_headers
            if self.session_info.network is not None
            else DOWNLOAD_HEADERS
        )

    def _run_segmented(  # pylint: disable=too-many-return-statements
        self, plan: TransferPlan, temp_path: Path, final_path: str, headers: dict[str, str],
    ) -> DownloadOutcome:
        manifest = plan.manifest
        assert manifest is not None
        self.live_manager.update_log(
            event="Download progress",
            details=(
                f"Segmented download: {len(manifest.segments)} x "
                f"{manifest.segments[0].length / (1024 * 1024):.1f} MB for {self.download_info.filename}"
            ),
        )
        manifest_reset = False
        for attempt in range(self.retries):
            outcome = SegmentedDownloader(
                url=self.download_info.download_link, headers=headers, temp_path=temp_path,
                manifest=manifest, progress_manager=self.live_manager, task=self.download_info.task,
            ).run()
            if outcome is SegmentedOutcome.COMPLETE:
                return finalise_download(
                    file_size=manifest.size, total_downloaded=manifest.size, temp_path=temp_path,
                    final_path=final_path, progress_manager=self.live_manager,
                    task=self.download_info.task, manifest_file=manifest_path(temp_path),
                )
            if outcome is SegmentedOutcome.NEEDS_REFRESH:
                fresh = self._refresh_link()
                if fresh is None:
                    return DownloadOutcome.RETRYABLE_FAILURE
                self.download_info.download_link = fresh
                continue
            if outcome is SegmentedOutcome.RANGE_UNSUPPORTED:
                discard_partial(temp_path)
                return self._run_single(
                    TransferPlan(TransferMode.SINGLE_NO_RESUME, None, plan.remote),
                    temp_path, final_path, headers,
                )
            if outcome is SegmentedOutcome.MANIFEST_INVALID:
                if manifest_reset:
                    return DownloadOutcome.TERMINAL_FAILURE
                discard_partial(temp_path)
                manifest = TransferManifest.plan(
                    manifest.size, len(manifest.segments), etag=manifest.etag, url_origin=manifest.url_origin,
                )
                manifest_reset = True
                continue
            if outcome is SegmentedOutcome.TERMINAL:
                return DownloadOutcome.TERMINAL_FAILURE
            if outcome is SegmentedOutcome.CANCELLED:
                return DownloadOutcome.RETRYABLE_FAILURE
            if not self._retry_with_backoff(attempt, event="Retrying download"):
                break
        return DownloadOutcome.RETRYABLE_FAILURE

    def _run_single(  # pylint: disable=too-many-return-statements
        self, plan: TransferPlan, temp_path: Path, final_path: str, headers: dict[str, str],
    ) -> DownloadOutcome:
        manifest = plan.manifest
        for attempt in range(self.retries):
            resume_from = manifest.segments[0].done if manifest is not None else 0
            request_headers = dict(headers)
            if resume_from:
                request_headers["Range"] = f"bytes={resume_from}-"
            try:
                response = requests.get(
                    self.download_info.download_link, stream=True, headers=request_headers, timeout=30,
                )
                if response.status_code == HTTPStatus.RANGE_NOT_SATISFIABLE and resume_from:
                    discard_partial(temp_path)
                    manifest = TransferManifest.plan(manifest.size, 1, etag=manifest.etag) if manifest else None
                    continue
                if response.status_code in (HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED):
                    fresh = self._refresh_link()
                    if fresh is not None:
                        self.download_info.download_link = fresh
                        continue
                response.raise_for_status()
            except RequestException as req_err:
                if not self._handle_request_exception(req_err, attempt):
                    break
                continue
            if resume_from and response.status_code != HTTPStatus.PARTIAL_CONTENT:
                # Server ignored our Range: start over so we never mix offsets.
                response.close()
                discard_partial(temp_path)
                if manifest is not None:
                    manifest.segments[0].done = 0
                continue
            return save_file_with_progress(
                response, final_path, self.download_info.task, self.live_manager,
                download_url=self.download_info.download_link, download_headers=headers,
                resume_from=resume_from if response.status_code == HTTPStatus.PARTIAL_CONTENT else 0,
                manifest=manifest,
            )
        return DownloadOutcome.RETRYABLE_FAILURE

    def _refresh_link(self) -> str | None:
        """Re-resolve the signed CDN URL from the item page; ``None`` if impossible."""
        item_page = self.download_info.item_page
        if not item_page:
            return None
        network = self.session_info.network
        page_headers = network.headers if network is not None else None
        try:
            page = requests.get(item_page, headers=page_headers, timeout=20)
            page.raise_for_status()
            soup = BeautifulSoup(page.text, "html.parser")
            link, _ = asyncio.run(get_download_info(item_page, soup, network=network))
        except (RequestException, RuntimeError, ValueError):
            return None
        if link:
            self.live_manager.update_log(
                event="Download progress",
                details=f"Signed URL expired; re-resolved {self.download_info.filename}.",
            )
        return link
```

Note: `save_file_with_progress` with `manifest` set derives `file_size` from the manifest; with a `206` response the `Content-Length` is the remainder, which Task 8 handles via `resume_from`. When `plan.mode is SINGLE_NO_RESUME`, `manifest is None` and the call is identical to today's.

- [ ] **Step 4: Run the full suite and lint**

Run: `.venv/bin/python -m pytest tests -q && .venv/bin/python -m pylint $(git ls-files '*.py') tests/unit/test_media_downloader_transfer.py tests/helpers/range_server.py`
Expected: all pass; pylint 10.00. If `media_downloader.py` trips `too-many-public-methods`/`too-many-branches`, move `_run_segmented`/`_run_single` into a small `TransferRunner` class in `segmented_download.py` taking `(media_downloader)`; keep names.

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/downloaders/media_downloader.py src/downloaders/download_utils.py tests/unit/test_media_downloader_transfer.py
git commit -m "feat(download): orchestrate probe, resume validation, segmentation and link refresh"
```

---

### Task 10: Stale partial cleanup at job start

**Files:**
- Modify: `src/downloaders/segmented_download.py` (append `cleanup_stale_partials`)
- Modify: `src/downloaders/album_downloader.py:169-183` (`download_album`)
- Test: `tests/unit/test_album_partial_cleanup.py`

**Interfaces:**
- Produces: `def cleanup_stale_partials(directory: Path, max_age_hours: int, *, now: float | None = None) -> list[Path]` returning the `.temp` paths removed (manifest removed alongside). `max_age_hours == 0` → no-op.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_album_partial_cleanup.py
"""Abandoned .temp/.temp.parts older than the knob are removed at job start."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.config import AlbumInfo
from src.downloaders.album_downloader import AlbumDownloader
from src.downloaders.segmented_download import cleanup_stale_partials


def _old(path: Path, hours: float) -> None:
    ts = time.time() - hours * 3600
    os.utime(path, (ts, ts))


def test_cleanup_removes_only_old_pairs(tmp_path: Path):
    old = tmp_path / "a.temp"; old.write_bytes(b"x"); (tmp_path / "a.temp.parts").write_text("{}")
    _old(old, 200); _old(tmp_path / "a.temp.parts", 200)
    fresh = tmp_path / "b.temp"; fresh.write_bytes(b"x"); (tmp_path / "b.temp.parts").write_text("{}")
    legacy = tmp_path / "c.temp"; legacy.write_bytes(b"x"); _old(legacy, 200)   # no manifest: left alone
    removed = cleanup_stale_partials(tmp_path, 168)
    assert removed == [old]
    assert not old.exists() and not (tmp_path / "a.temp.parts").exists()
    assert fresh.exists() and (tmp_path / "b.temp.parts").exists() and legacy.exists()


def test_cleanup_disabled_with_zero(tmp_path: Path):
    old = tmp_path / "a.temp"; old.write_bytes(b"x"); (tmp_path / "a.temp.parts").write_text("{}")
    _old(old, 1000); _old(tmp_path / "a.temp.parts", 1000)
    assert cleanup_stale_partials(tmp_path, 0) == [] and old.exists()


def test_download_album_runs_cleanup_with_job_setting(fake_live_manager, session_info):
    class Args:  # pylint: disable=too-few-public-methods
        partial_max_age_hours = 5
        max_workers = 1
    session_info.args = Args()
    album = AlbumDownloader(session_info=session_info, album_info=AlbumInfo(album_id="x", item_pages=[]),
                            live_manager=fake_live_manager)
    with patch("src.downloaders.album_downloader.cleanup_stale_partials", return_value=[Path("/d/a.temp")]) as cl, \
         patch.object(album, "_process_failed_downloads", new=AsyncMock()):
        asyncio.run(album.download_album(max_workers=1))
    cl.assert_called_once()
    assert cl.call_args.args[1] == 5
    assert any("a.temp" in d for _, d in fake_live_manager.logs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_album_partial_cleanup.py -q`
Expected: FAIL — `ImportError: cannot import name 'cleanup_stale_partials'`.

- [ ] **Step 3: Implement**

Append to `segmented_download.py`:

```python
def cleanup_stale_partials(
    directory: Path, max_age_hours: int, *, now: float | None = None,
) -> list[Path]:
    """Delete ``*.temp`` + ``*.temp.parts`` pairs older than ``max_age_hours``.

    Only pairs are touched: a lone ``.temp`` from an older build has no
    manifest and is left for the existing "discard on next attempt" path.
    ``0`` disables the sweep.
    """
    if max_age_hours <= 0 or not directory.is_dir():
        return []
    cutoff = (now if now is not None else time.time()) - max_age_hours * 3600
    removed: list[Path] = []
    for parts in sorted(directory.glob("*.temp.parts")):
        temp = parts.with_name(parts.name[: -len(".parts")])
        try:
            newest = max(parts.stat().st_mtime, temp.stat().st_mtime if temp.exists() else 0)
        except OSError:
            continue
        if newest >= cutoff:
            continue
        for path in (temp, parts):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        removed.append(temp)
    return removed
```

(add `import time` to the module imports.)

In `album_downloader.py`, import `cleanup_stale_partials` and `resolve_transfer_settings`, then at the top of `download_album` before `add_overall_task`:

```python
        settings = resolve_transfer_settings(self.session_info.args)
        removed = cleanup_stale_partials(
            Path(self.session_info.download_path), settings.partial_max_age_hours,
        )
        for path in removed:
            self.live_manager.update_log(
                event="Stale partial removed",
                details=f"Deleted abandoned partial download {path.name}",
            )
```

(add `from pathlib import Path` to `album_downloader.py` imports.)

- [ ] **Step 4: Run tests and lint**

Run: `.venv/bin/python -m pytest tests/unit/test_album_partial_cleanup.py tests/unit/test_item_page_maintenance.py -q && .venv/bin/python -m pylint src/downloaders tests/unit/test_album_partial_cleanup.py`
Expected: pass; pylint clean.

- [ ] **Step 5: Commit**

```bash
git add src/downloaders/segmented_download.py src/downloaders/album_downloader.py tests/unit/test_album_partial_cleanup.py
git commit -m "feat(download): sweep abandoned partial downloads at job start"
```

---

### Task 11: Web API — request fields, namespace precedence, settings defaults

**Files:**
- Modify: `src/web/app.py` — `DownloadRequest`, `_build_namespace`, `get_settings_defaults`
- Test: `tests/unit/test_web_transfer_settings.py`

**Interfaces:**
- Produces:
  - `DownloadRequest` gains `segments: int | None = Field(default=None, ge=1, le=16)`, `segment_min_size_mb: int | None = Field(default=None, ge=1, le=4096)`, `max_connections: int | None = Field(default=None, ge=1, le=64)`, `partial_max_age_hours: int | None = Field(default=None, ge=0, le=8760)`.
  - `_build_namespace` copies them verbatim (`None` preserved; `resolve_transfer_settings` applies env defaults).
  - `GET /api/settings/defaults` → `{"network": {...}, "download": {"max_workers": int, "segments": int, "segment_min_size_mb": int, "max_connections": int, "partial_max_age_hours": int}}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_web_transfer_settings.py
"""Transfer knobs over the web API: validation, precedence, defaults endpoint."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

from fastapi.testclient import TestClient

from src.web.app import DownloadRequest, _build_namespace, app


def test_settings_defaults_exposes_download_section():
    with TestClient(app) as client:
        body = client.get("/api/settings/defaults").json()
    assert body["download"] == {
        "max_workers": 3, "segments": 4, "segment_min_size_mb": 32,
        "max_connections": 12, "partial_max_age_hours": 168,
    }


def test_request_fields_validated():
    with TestClient(app) as client:
        resp = client.post("/api/downloads", json={"urls": ["https://bunkr.cr/a/x"], "segments": 99})
    assert resp.status_code == 422


def test_namespace_preserves_absent_and_present_fields():
    req = DownloadRequest(urls=["https://bunkr.cr/a/x"])
    ns = _build_namespace("https://bunkr.cr/a/x", req)
    assert ns.segments is None and ns.max_connections is None
    req = DownloadRequest(urls=["https://bunkr.cr/a/x"], segments=2, segment_min_size_mb=64,
                          max_connections=5, partial_max_age_hours=0)
    ns = _build_namespace("https://bunkr.cr/a/x", req)
    assert (ns.segments, ns.segment_min_size_mb, ns.max_connections, ns.partial_max_age_hours) == (2, 64, 5, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_web_transfer_settings.py -q`
Expected: FAIL (`KeyError: 'download'`, 200 instead of 422, `AttributeError: segments`).

- [ ] **Step 3: Implement**

In `DownloadRequest` after `max_workers`:

```python
    segments: int | None = Field(default=None, ge=1, le=16,
                                 description="Parallel byte ranges per file; omit to use the server default.")
    segment_min_size_mb: int | None = Field(default=None, ge=1, le=4096,
                                            description="Files below this size use a single stream.")
    max_connections: int | None = Field(default=None, ge=1, le=64,
                                        description="Process-wide cap on simultaneous download connections.")
    partial_max_age_hours: int | None = Field(default=None, ge=0, le=8760,
                                              description="Delete abandoned partials older than this; 0 disables.")
```

In `_build_namespace` add to the `Namespace(...)`:

```python
        segments=request.segments,
        segment_min_size_mb=request.segment_min_size_mb,
        max_connections=request.max_connections,
        partial_max_age_hours=request.partial_max_age_hours,
```

Replace `get_settings_defaults`:

```python
@app.get("/api/settings/defaults")
async def get_settings_defaults() -> dict[str, dict[str, Any]]:
    """Return server-resolved defaults (built-in < env) so the UI can seed its settings."""
    transfer = resolve_transfer_settings(None)
    return {
        "network": get_network_settings(),
        "download": {
            "max_workers": MAX_WORKERS,
            "segments": transfer.segments,
            "segment_min_size_mb": transfer.segment_min_bytes // (1024 * 1024),
            "max_connections": transfer.max_connections,
            "partial_max_age_hours": transfer.partial_max_age_hours,
        },
    }
```

(import `resolve_transfer_settings` from `src.config`; `MAX_WORKERS` and `Any` are already imported in `app.py`.)

- [ ] **Step 4: Run tests and lint**

Run: `.venv/bin/python -m pytest tests/unit/test_web_transfer_settings.py tests/integration -q && .venv/bin/python -m pylint src/web/app.py tests/unit/test_web_transfer_settings.py`
Expected: pass; pylint clean.

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py tests/unit/test_web_transfer_settings.py
git commit -m "feat(web): transfer knobs on DownloadRequest and settings defaults"
```

---

### Task 12: Frontend — Transfer settings group, server-default seeding, payload

**Files:**
- Modify: `frontend/src/App.tsx` (settings type/defaults, seeding effect), `frontend/src/components/settings/SettingsPanel.tsx` (Transfer card + reset), `frontend/src/components/download/DownloadForm.tsx` (payload)

**Interfaces:**
- Consumes: `GET /api/settings/defaults` → `download` section (Task 11); `POST /api/downloads` fields (Task 11).
- Produces: `AppSettings`/`Settings` gain `segments: number; segmentMinSizeMb: number; maxConnections: number; partialMaxAgeHours: number`.

- [ ] **Step 1: Extend the settings type in all three files** (`App.tsx` `AppSettings`, `SettingsPanel.tsx` `Settings`, `DownloadForm.tsx` `Settings` — they are three identical local interfaces today; add the four fields to each):

```ts
  segments: number;
  segmentMinSizeMb: number;
  maxConnections: number;
  partialMaxAgeHours: number;
```

and in `App.tsx` `DEFAULT_SETTINGS` add:

```ts
  segments: 4,
  segmentMinSizeMb: 32,
  maxConnections: 12,
  partialMaxAgeHours: 168,
```

- [ ] **Step 2: Seed from the server on first load** (`App.tsx`, after the `/meta` effect):

```ts
  // Seed the Transfer group from the server once per browser so env-set
  // defaults show up in the UI; a user's saved values are never overwritten.
  useEffect(() => {
    let seeded = false;
    try { seeded = window.localStorage.getItem(SEEDED_KEY) === "1"; } catch { /* ignore */ }
    if (seeded) return;
    void api.get<ServerDefaults>("/settings/defaults").then(({ data }) => {
      const d = data?.download;
      if (!d) return;
      setSettings((prev) => ({
        ...prev,
        maxWorkers: d.max_workers ?? prev.maxWorkers,
        segments: d.segments ?? prev.segments,
        segmentMinSizeMb: d.segment_min_size_mb ?? prev.segmentMinSizeMb,
        maxConnections: d.max_connections ?? prev.maxConnections,
        partialMaxAgeHours: d.partial_max_age_hours ?? prev.partialMaxAgeHours,
      }));
      try { window.localStorage.setItem(SEEDED_KEY, "1"); } catch { /* ignore */ }
    }).catch(() => void 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
```

with, near `DEFAULT_SETTINGS`:

```ts
const SEEDED_KEY = "bunkrdownloader:transfer-seeded-v1";

interface ServerDefaults {
  download?: {
    max_workers?: number;
    segments?: number;
    segment_min_size_mb?: number;
    max_connections?: number;
    partial_max_age_hours?: number;
  };
}
```

and a reset handler passed to the panel:

```ts
  const resetTransferDefaults = async () => {
    try {
      const { data } = await api.get<ServerDefaults>("/settings/defaults");
      const d = data?.download;
      if (!d) return;
      setSettings((prev) => ({
        ...prev,
        segments: d.segments ?? prev.segments,
        segmentMinSizeMb: d.segment_min_size_mb ?? prev.segmentMinSizeMb,
        maxConnections: d.max_connections ?? prev.maxConnections,
        partialMaxAgeHours: d.partial_max_age_hours ?? prev.partialMaxAgeHours,
      }));
      toast({ title: "Transfer settings reset to server defaults", status: "info" });
    } catch {
      toast({ title: "Could not load server defaults", status: "error" });
    }
  };
```

Pass `onResetTransfer={resetTransferDefaults}` to `<SettingsPanel …/>`.

- [ ] **Step 3: Add the Transfer card to `SettingsPanel.tsx`** (new prop `onResetTransfer: () => void`; new imports `Button`, `Tooltip` from Chakra). Insert between the Runtime and Network cards:

```tsx
      <Surface variant="card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-3)" }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Transfer</h2>
          <Button size="sm" variant="ghost" onClick={onResetTransfer}>Reset to server defaults</Button>
        </div>
        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
          <NumberSetting label="Parallel segments per file" tip="1–16. Large files are fetched as this many byte ranges at once; 1 = single stream (still resumable)."
            value={settings.segments} min={1} max={16} fallback={4}
            onChange={(n) => onChange({ segments: n })} />
          <NumberSetting label="Minimum file size to segment (MB)" tip="1–4096. Smaller files use one stream; also the smallest size a single segment may have."
            value={settings.segmentMinSizeMb} min={1} max={4096} fallback={32}
            onChange={(n) => onChange({ segmentMinSizeMb: n })} />
          <NumberSetting label="Max simultaneous connections" tip="1–64. Cap across all workers and segments. Bunkr rate-limits bulk activity per IP."
            value={settings.maxConnections} min={1} max={64} fallback={12}
            onChange={(n) => onChange({ maxConnections: n })} />
          <NumberSetting label="Delete abandoned partials after (hours)" tip="0–8760. Partial .temp files older than this are removed when a job starts; 0 keeps them forever."
            value={settings.partialMaxAgeHours} min={0} max={8760} fallback={168}
            onChange={(n) => onChange({ partialMaxAgeHours: n })} />
        </SimpleGrid>
      </Surface>
```

with a small local component in the same file:

```tsx
interface NumberSettingProps {
  label: string;
  tip: string;
  value: number;
  min: number;
  max: number;
  fallback: number;
  onChange: (n: number) => void;
}

function NumberSetting({ label, tip, value, min, max, fallback, onChange }: NumberSettingProps) {
  return (
    <FormControl>
      <Tooltip label={tip} hasArrow openDelay={300}>
        <FormLabel>{label}</FormLabel>
      </Tooltip>
      <NumberInput min={min} max={max} value={value}
        onChange={(_, n) => onChange(Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback)}>
        <NumberInputField />
        <NumberInputStepper>
          <NumberIncrementStepper />
          <NumberDecrementStepper />
        </NumberInputStepper>
      </NumberInput>
    </FormControl>
  );
}
```

- [ ] **Step 4: Send the values with each job** (`DownloadForm.tsx` payload, after `max_workers`):

```ts
        segments: settings.segments,
        segment_min_size_mb: settings.segmentMinSizeMb,
        max_connections: settings.maxConnections,
        partial_max_age_hours: settings.partialMaxAgeHours,
```

- [ ] **Step 5: Typecheck, build, and a real browser check**

Run: `cd frontend && npm run typecheck && npm run build`
Expected: both succeed.

Then from the repo root, in the scratchpad: start `DOWNLOAD_SEGMENTS=2 .venv/bin/python -m uvicorn src.web.app:app --app-dir . --host 127.0.0.1 --port 8765`, open `http://127.0.0.1:8765/` with the Playwright tools in a fresh browser profile, go to the Settings tab and confirm the Transfer card shows **2** segments (env seeded), change it to 3, reload, confirm it stays 3 (persisted, not re-seeded), click "Reset to server defaults", confirm 2. Stop the server by port (`ss -ltnp | grep 8765`), never with a `pkill -f` pattern that matches your own shell.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/settings/SettingsPanel.tsx frontend/src/components/download/DownloadForm.tsx
git commit -m "feat(web): Transfer settings group seeded from server defaults"
```

---

### Task 13: Docs, compose forwarding, env sample, CLAUDE.md, final gate

**Files:**
- Modify: `README.md` (Environment Variables table, new "Transfer & resume" bullets under Configuration, CLI Usage flags), `.env.sample`, `docker-compose.yml`, `docker-compose.vpn.yml`, `CLAUDE.md`

- [ ] **Step 1: Compose and env sample**

Add under `MAINTENANCE_BACKOFF_DELAYS_SECONDS` in **both** compose files' `environment:`:

```yaml
      DOWNLOAD_SEGMENTS: ${DOWNLOAD_SEGMENTS:-4}
      SEGMENT_MIN_FILE_SIZE_MB: ${SEGMENT_MIN_FILE_SIZE_MB:-32}
      MAX_CONCURRENT_CONNECTIONS: ${MAX_CONCURRENT_CONNECTIONS:-12}
      PARTIAL_MAX_AGE_HOURS: ${PARTIAL_MAX_AGE_HOURS:-168}
```

Append to `.env.sample` before the "Container image tag" line:

```
# ---------------------------------------------------------------------------
# Transfer: segmented + resumable downloads
# ---------------------------------------------------------------------------
# Parallel byte ranges per file (1-16); 1 = single stream, still resumable.
#DOWNLOAD_SEGMENTS=4
# Files smaller than this (MB, 1-4096) use a single stream.
#SEGMENT_MIN_FILE_SIZE_MB=32
# Process-wide cap on simultaneous download connections (1-64).
#MAX_CONCURRENT_CONNECTIONS=12
# Delete abandoned .temp/.temp.parts older than this at job start (hours, 0 disables).
#PARTIAL_MAX_AGE_HOURS=168
```

- [ ] **Step 2: README**

Table rows (after `MAINTENANCE_BACKOFF_DELAYS_SECONDS`):

```
| `DOWNLOAD_SEGMENTS` 🆕 | Parallel byte ranges per file (1–16). `1` = single stream, still resumable. The web Settings page can override per job. | `4` |
| `SEGMENT_MIN_FILE_SIZE_MB` 🆕 | Files below this size use a single stream; also the minimum size of one segment (1–4096). | `32` |
| `MAX_CONCURRENT_CONNECTIONS` 🆕 | Cap on simultaneous download connections across all workers and segments (1–64). | `12` |
| `PARTIAL_MAX_AGE_HOURS` 🆕 | Abandoned `.temp` + `.temp.parts` pairs older than this are deleted when a job starts; `0` disables (0–8760). | `168` |
```

Configuration bullets (append):

```
- 🆕 **Segmented transfer**: large files are fetched as several byte ranges in parallel into one pre-sized `.temp` file. Tune with `DOWNLOAD_SEGMENTS` / `SEGMENT_MIN_FILE_SIZE_MB` / `MAX_CONCURRENT_CONNECTIONS`, or per job from the web **Settings → Transfer** group (server/env values are the defaults; your saved values win).
- 🆕 **Resume**: every transfer keeps a small `<name>.temp.parts` manifest (remote size, ETag, per-segment progress). A download interrupted by a network error, an expired link, a cancel or a restart continues from the bytes already on disk — on the next retry **and** on a later run of the same URL — as long as the remote size/ETag still match. Abandoned partials are swept after `PARTIAL_MAX_AGE_HOURS`.
```

CLI Usage line: add `[--segments N] [--segment-min-size-mb MB] [--max-connections N] [--partial-max-age-hours H]` to the single-URL synopsis and one bullet: `- `--segments` 🆕 parallel ranges per file (1–16); the other three transfer flags mirror the env knobs above.`

- [ ] **Step 3: CLAUDE.md**

Replace the `src/downloaders/` bullet under "Crawlers vs downloaders" with:

```
- `src/downloaders/` — `AlbumDownloader` orchestrates a thread pool of `MediaDownloader` workers (`asyncio.to_thread`). Per file, `MediaDownloader.attempt_download` does: one HEAD (`remote_probe.probe_remote`) → validate any existing `<name>.temp.parts` manifest against size/ETag (`transfer_manifest`) → `segmented_download.plan_transfer` → either `SegmentedDownloader` (N range workers `pwrite`-ing into one pre-sized `.temp`, manifest flushed every 8 MiB) or `download_utils.save_file_with_progress` (single stream, `Range` resume from the manifest). 401/403 mid-transfer means the signed URL expired: `_refresh_link()` re-resolves via the item page and workers restart against the same manifest. A process-wide `connection_governor.GOVERNOR` caps streaming GETs (`MAX_CONCURRENT_CONNECTIONS`, raised to at least `max_workers`). `DownloadOutcome` (`SUCCESS / RETRYABLE_FAILURE / TERMINAL_FAILURE`) stays the boundary. Knobs resolve via `config.resolve_transfer_settings(args)` (built-in < env < per-job). Tests use `tests/helpers/range_server.py`.
```

and add to Conventions: ``- Partial downloads are **resumable across runs**: never delete `*.temp.parts` in code paths other than `transfer_manifest.discard_partial` / `cleanup_stale_partials`.``

- [ ] **Step 4: Full gate, compose validation, image build**

Run:
```bash
.venv/bin/python -m compileall -q src downloader.py main.py
.venv/bin/python -m pylint $(git ls-files '*.py')
.venv/bin/python -m pytest tests smoke_tests -q
docker compose config | grep -c "DOWNLOAD_SEGMENTS\|SEGMENT_MIN_FILE_SIZE_MB\|MAX_CONCURRENT_CONNECTIONS\|PARTIAL_MAX_AGE_HOURS"
WIREGUARD_PRIVATE_KEY=x WIREGUARD_ADDRESSES=10.0.0.2/16 docker compose -f docker-compose.vpn.yml config | grep -c "DOWNLOAD_SEGMENTS\|SEGMENT_MIN_FILE_SIZE_MB\|MAX_CONCURRENT_CONNECTIONS\|PARTIAL_MAX_AGE_HOURS"
docker build -q -t bunkr-segtest --build-arg APP_VERSION=segtest . && docker rmi -f bunkr-segtest
```
Expected: compile OK; pylint 10.00 with exit 0; all tests pass; both greps print `4`; image builds.

- [ ] **Step 5: Real-world check (dev box, no VPN)**

Run the CLI against one album with `--segments 4 --include <a term matching exactly one large file>` into a scratch `--custom-path`; kill it with Ctrl-C at ~30 %; rerun the same command; confirm the log shows `Resuming …: NN% already on disk` and the finished file's SHA-256 equals a single-stream (`--segments 1`) download of the same file. Record the two hashes in the PR description.

- [ ] **Step 6: Commit and open the PR**

```bash
git add README.md .env.sample docker-compose.yml docker-compose.vpn.yml CLAUDE.md
git commit -m "docs(download): document segmented/resumable transfer knobs"
git push -u origin feat/segmented-resumable-downloads
gh pr create --base main --title "feat(download): segmented, resumable transfers" --body "$(cat <<'EOF'
## Summary
Implements docs/superpowers/specs/2026-10-21-segmented-resumable-downloads-design.md.
- Large files download as N parallel byte ranges into one pre-sized `.temp`; a `.temp.parts` manifest (size, ETag, per-segment progress) makes every transfer resumable on retry and on later runs.
- Expired signed URLs (401/403 mid-file) re-resolve via the item page and workers restart against the same manifest.
- Knobs: DOWNLOAD_SEGMENTS (4), SEGMENT_MIN_FILE_SIZE_MB (32), MAX_CONCURRENT_CONNECTIONS (12), PARTIAL_MAX_AGE_HOURS (168); built-in < env < per-job; CLI flags; web Settings → Transfer group seeded from /api/settings/defaults.
- Abandoned partials swept at job start after PARTIAL_MAX_AGE_HOURS.

## Verification
- Unit: manifest math/round-trip/validation, probe, governor, plan_transfer, SegmentedDownloader (full, resume, 200-fallback, 403→refresh, mid-stream abort, cancel, governor cap, ENOSPC, 416), single-stream resume, MediaDownloader orchestration, cleanup sweep, web validation/precedence/defaults.
- CI gate: compileall, pylint 10.00, pytest all green; both compose files render the four knobs; Docker image builds.
- Real: segmented download of <file> interrupted at ~30% and resumed; SHA-256 <hash> equals single-stream SHA-256 <hash>.
EOF
)"
```

Merging produces a minor release (v0.15.0 if v0.14.0 from the re-attach PR has already been cut). After release: README "Latest Release Updates" entry in a `docs(readme):` PR.
