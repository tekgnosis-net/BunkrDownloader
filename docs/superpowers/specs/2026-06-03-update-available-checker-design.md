# Periodic release checker — design

**Date:** 2026-06-03
**Status:** Approved (pending spec review)
**Scope:** Web UI only. The check is always on (no opt-out toggle).

## Goal

Surface an "update available: vX.Y.Z" notice directly under the version badge in
the web UI when the running build is older than the latest published GitHub
release of `tekgnosis-net/BunkrDownloader`.

## Non-goals

- No CLI/batch notice (web UI only).
- No env toggle to disable the check (always on).
- No auto-update / download-the-new-version behaviour — informational only.
- No persistence; the check is recomputed at runtime, not baked at build time.

## Architecture

Backend proxy endpoint with a shared TTL cache. The browser never calls GitHub
directly — the FastAPI backend fetches the latest release at most once per TTL
window, compares versions server-side, and hands the frontend a ready-to-render
verdict.

Rationale: a single shared upstream request per TTL avoids the unauthenticated
60-req/hr/IP GitHub limit, sidesteps CORS, keeps every user's IP off GitHub, and
puts the only non-trivial logic (semver parsing, "am I ahead?", GitHub-down
handling) in Python where the test suite (pylint 10.0 + pytest) can guard it.
The frontend stays a dumb renderer. This mirrors the existing outbound-HTTP +
module-level TTL cache pattern in `src/bunkr_utils.py::_status_cache`.

## Components

### `src/web/update_check.py` (new)

Pure, testable logic plus the cached fetch.

- `parse_version(text: str) -> tuple[int, int, int] | None`
  Strips a single leading `v`/`V`, matches `^(\d+)\.(\d+)\.(\d+)`, returns the
  int triple or `None` when it doesn't match. `None` means "unknown" and never
  triggers an update (so `"dev"`, `"1.2"`, `""` are inert).

- `is_update_available(current: str, latest: str) -> bool`
  Returns `True` only when both parse and `latest > current` as int tuples.
  Equal → `False`; running ahead of latest → `False`; either unparseable →
  `False`.

- `get_latest_release(*, now: float | None = None) -> str | None`
  `requests.get` to
  `https://api.github.com/repos/tekgnosis-net/BunkrDownloader/releases/latest`
  with a 5s timeout and `Accept: application/vnd.github+json`, returning the
  response's `tag_name`. Guarded by a module-level cache
  `(_fetched_at: float | None, _cached_tag: str | None)` behind a
  `threading.Lock`, TTL = 6 hours (`UPDATE_CHECK_TTL_SECONDS = 6 * 3600`).
  Cache validity is keyed on `_fetched_at` alone: `None` means "never fetched"
  (forces a fetch); a non-`None` timestamp within the TTL means "return
  `_cached_tag` as-is, even if it is `None`." On any
  `requests.RequestException`, non-200, or missing/invalid `tag_name`, returns
  `None` and caches that `None` (stamping `_fetched_at`) for the same TTL window
  so a GitHub outage cannot be hammered. `now` is injectable for deterministic
  TTL tests; defaults to `time.monotonic()`.

- `get_update_status(current: str) -> dict`
  Orchestrates the above into
  `{"current_version": current, "latest_version": <tag|None>,
    "update_available": <bool>}`.

### `src/web/app.py` (endpoint)

- `UpdateStatusResponse(BaseModel)` with `current_version: str`,
  `latest_version: str | None`, `update_available: bool`.
- `GET /api/update-check` defined as a **sync `def`** (not `async`) so Starlette
  runs the blocking `requests` call in its threadpool and never blocks the event
  loop. Body: `return UpdateStatusResponse(**get_update_status(APP_VERSION))`.
  Always returns 200; GitHub unreachable collapses to `update_available: false`.

### Frontend

- `frontend/src/lib/api.ts` — unchanged (shared axios instance reused).
- `frontend/src/App.tsx`
  - New state `updateInfo: { latestVersion: string | null; updateAvailable: boolean }`.
  - `useEffect`: fetch `/update-check` on mount, then `setInterval` every 6 hours;
    clear the interval on unmount. Failures are swallowed (`.catch(() => void 0)`),
    leaving `updateAvailable: false`.
  - Pass `latestVersion` and `updateAvailable` into `TopBar`.
- `frontend/src/components/shell/TopBar.tsx`
  - New props `latestVersion: string | null`, `updateAvailable: boolean`.
  - Wrap the existing `v{appVersion}` pill in a vertical flex column so a second
    element can sit directly beneath it.
  - When `updateAvailable`, render a small pill **under** the version:
    `↑ update available: v{latestVersion}`, as an external link to
    `https://github.com/tekgnosis-net/BunkrDownloader/releases`
    (`target="_blank"`, `rel="noopener noreferrer"`), styled with a subtle accent
    so it reads as actionable. When `false`, render nothing.

## Data flow

```
GitHub releases/latest
        │ (≤ once per 6h, server-side)
        ▼
src/web/update_check.get_latest_release ──► get_update_status(APP_VERSION)
        │
        ▼
GET /api/update-check ──► { current_version, latest_version, update_available }
        │ (mount + every 6h)
        ▼
App.tsx updateInfo ──► TopBar ──► "↑ update available: vX.Y.Z" pill (link)
```

## Error handling

Every failure path collapses to "no update available," never an error the UI must
handle:

- GitHub timeout / `RequestException` / non-200 → `get_latest_release` returns
  `None` (cached for the TTL window) → `update_available: false`.
- Malformed or missing `tag_name` → `None` → `update_available: false`.
- Unparseable current or latest version → `is_update_available` returns `False`.
- Frontend fetch error → caught, `updateAvailable` stays `false`.

## Testing (TDD — RED first)

`tests/unit/test_update_check.py`:

- `parse_version`: `"0.11.5"`→`(0,11,5)`; `"v0.11.5"`→`(0,11,5)`; rejects `"dev"`,
  `"1.2"`, `""`, `"v"` → `None`.
- `is_update_available`: newer→`True`; equal→`False`; older/ahead→`False`;
  unparseable either side→`False`.
- `get_latest_release` caching: two calls within the TTL → exactly one patched
  `requests.get`; advancing injected `now` past the TTL → a second fetch.
- GitHub failure: patched `requests.get` raising `RequestException` →
  `get_latest_release` returns `None`; `get_update_status` →
  `update_available: false`, no exception; the `None` is cached.
- Endpoint via FastAPI `TestClient`: patched latest yields
  `{update_available: true, latest_version: "v9.9.9", current_version: APP_VERSION}`.

Cache isolation: tests reset the module-level cache (helper or direct attribute
reset) so ordering can't leak state between cases.

Frontend: no JS test runner exists in CI (only `npm run build`); the frontend is
deliberately logic-free, validated by the build plus manual smoke. All edge-case
logic lives in the tested Python layer.

## Delivery

- Conventional Commits: the feature commit is `feat:` → semantic-release minor
  bump.
- Branch → PR → review → merge per project norm. Per
  `[[feedback-copilot-review-policy]]`, request Copilot only if the diff is
  non-trivial; otherwise self-review.
- After release, refresh the README "Latest Release Updates" section per
  `[[feedback-readme-release-notes]]`.

## Config / constants

- `UPDATE_CHECK_TTL_SECONDS = 6 * 3600` in `src/web/update_check.py`.
- `GITHUB_LATEST_RELEASE_URL =
  "https://api.github.com/repos/tekgnosis-net/BunkrDownloader/releases/latest"`.
- No new env vars (always-on, no toggle).
