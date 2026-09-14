# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Dev setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime deps + pytest, pytest-asyncio, pytest-timeout, httpx, pylint
```

### CI gate (runs on every push/PR in `.github/workflows/ci.yml`)
```bash
python -m compileall -q src downloader.py main.py
python -m pylint $(git ls-files '*.py')
python -m pytest tests smoke_tests -v --durations=10
```
All three must pass on Python 3.10 and 3.11. Pylint is held at 10.00/10; `.pylintrc` already whitelists `duplicate-code` and `too-many-return-statements` (with `max-returns=8`). `pyproject.toml` sets `asyncio_mode = "auto"` so coroutine tests don't need `@pytest.mark.asyncio`, and `timeout = 30` (pytest-timeout) so a hung WebSocket test fails instead of stalling CI.

Frontend sanity:
```bash
cd frontend && npm install && npm run typecheck && npm run build
```
`npm run typecheck` (`tsc --noEmit`) is not part of CI yet, but the Docker build runs the same Vite/TS toolchain, so type errors surface there.

### Running a single test
```bash
python -m pytest tests/unit/test_event_broker.py::test_subscribe_does_not_drop_events_during_replay -v
```

### Running the app
```bash
# CLI (single URL)
python3 downloader.py <bunkr_url> [--include term ...] [--ignore term ...] [--custom-path /path] [--disable-ui]

# CLI (batch — reads URLs.txt, writes session.log, clears URLs.txt on completion)
python3 main.py

# Web stack (local dev)
uvicorn src.web.app:app --reload          # backend on :8000
cd frontend && npm install && npm run dev  # Vite dev server proxies /api and /ws to VITE_API_PROXY

# Full stack via Docker
docker compose up --build

# Behind a VPN (gluetun + Surfshark WireGuard) — standalone file, NOT an override
docker compose -f docker-compose.vpn.yml up -d
```
`docker-compose.vpn.yml` duplicates the `bunkr` service on purpose (`network_mode: service:gluetun` forbids `ports`, and overrides can't remove them); keep it in sync when the base compose changes.
Note: `.env.sample` sets `API_PORT=8887` and `VITE_API_PROXY=http://localhost:8887`, while `docker-compose.yml` and `vite.config.js` default to 8000. If you copy the sample, the ports line up with each other but not with a bare `uvicorn` on 8000.

### Release
Releases are driven by **python-semantic-release** via `.github/workflows/semantic-release.yml` and the Angular commit-parser config in `pyproject.toml`. Use Conventional Commits (`feat:`, `fix:`, `docs:`, ...) — commit subjects drive version bumps and CHANGELOG generation. The `v{version}` tag is what `IMAGE_TAG` pins in `docker-compose.yml`.

**Version gotcha:** the release commit only touches `CHANGELOG.md`; `pyproject.toml` still says `0.3.3` while tags are at `v0.12.x`. `src/__init__.py::_derive_version` resolves `APP_VERSION` env → `importlib.metadata` → `pyproject.toml`, and ignores the literal value `latest`. So a local `uvicorn` run reports `0.3.3` (and the update badge always fires), while the container gets the real version because the release workflow passes `--build-arg APP_VERSION=<version>`. Don't "fix" a stale badge locally by editing pyproject.

After every release, refresh the README "Latest Release Updates" section (newest entry on top) in a `docs(readme):` commit.

## Architecture

### Single download pipeline, three front-doors
`downloader.py::validate_and_download` is the one entrypoint that actually performs a download. Three callers wrap it:

1. `downloader.py::main` — single-URL CLI with full argparse.
2. `main.py::process_urls` — batch CLI that reads `URLs.txt`, calls `parse_arguments(common_only=True)` (no URL/filter args), and loops over `validate_and_download` inside a single `LiveManager.live` context.
3. `src/web/app.py::_run_download_job` — FastAPI wraps the same `validate_and_download` import and constructs an `argparse.Namespace` in-memory from the Pydantic `DownloadRequest` before handing control to it.

**Consequence for any change to the download flow:** it must keep working with (a) a Rich `LiveManager` producing terminal output, (b) the batch loop reusing one manager across URLs, and (c) a `WebLiveManager` whose `update_log`/progress/`update_maintenance` calls are mirrored into a `JobEventBroker` queue.

### Progress + log abstraction (`src/managers/` + `src/web/app.py`)
CLI uses `LiveManager` (wraps `ProgressManager` + `LoggerTable` inside a Rich `Live`). `initialize_managers(disable_ui=..., log_level=...)` is called by every entrypoint. `WebLiveManager` in `src/web/app.py` implements the **same method surface** (`add_overall_task`, `add_task`, `update_task`, `update_log`, `log_debug`, `update_maintenance`, `stop`) so `validate_and_download` is oblivious to which one it has. `tests/conftest.py::FakeLiveManager` is a third implementation used by unit tests. **When adding a new method to the contract, add it to all three in the same PR** or the web UI (or the tests) will silently diverge from the CLI.

### Session + network context
`SessionInfo` (dataclass in `src/config.py`) carries `(args, bunkr_status, download_path, network)` through the pipeline. `network` is a `NetworkContext` — a **frozen** dataclass with `status_page`, `bunkr_api`, `fallback_domain`, `user_agent`, `download_referer` and `.headers` / `.download_headers` properties. It is the **authoritative per-job networking source**. Build one with `build_network_context(args, overrides=…)` and read from it instead of importing the module-level `HEADERS`/`BUNKR_API`/`STATUS_PAGE`/`FALLBACK_DOMAIN` globals in new code. The globals still serve CLI-process defaults (set once via `apply_argument_overrides` at startup) but must not be mutated per job — the web layer used to do that, which let concurrent jobs clobber each other.

Every downloader-chain function accepts an optional `network=` kwarg: `fetch_page`, `get_api_response`, `get_download_info`, `extract_all_album_item_pages`, `refresh_server_status`, `get_bunkr_status`, `get_bunkr_status_cached`, `change_domain_to_cr`, `validate_download_link`. Pass `network=session_info.network` from any new call site in the download pipeline.

`bunkr_api` is a legacy field: the `/api/vs` endpoint it points at is retired (see Crawlers below). It survives so the web `NetworkOverrides.api_endpoint` override and old tests still type-check; don't build new logic on it.

### Crawlers vs downloaders
- `src/crawlers/` — HTML/API scraping only. `crawler_utils` walks album pagination (`extract_all_album_item_pages`) and item pages (`get_download_info`). `api_utils` resolves the actual media URL: Bunkr retired `POST /api/vs` + XOR decrypt in mid-2026, so item pages now embed `var jsCDN = "…"` (raw CDN URL) and `var signUrl = "…"` (signing endpoint). `get_signed_download_url` reads both, GETs `{signUrl}?path=<cdn path>` for a short-lived `{token, ex}` pair, and appends them to the CDN URL. Because `signUrl` comes from page content on a user-supplied URL, `_is_trusted_sign_url` requires HTTPS plus a host in `SIGN_URL_ALLOWED_HOSTS` (env `BUNKR_SIGN_ALLOWED_HOSTS`, default `cdn.cr`, suffix match) — this is an SSRF guard, keep it when touching the flow. Tests: `tests/unit/test_signed_url.py`.
- `src/downloaders/` — `AlbumDownloader` orchestrates a thread pool of `MediaDownloader` workers (`asyncio.to_thread`). `download_utils.save_file_with_progress` does chunked writes, picking chunk size from `THRESHOLDS` in `config.py`; it returns a `DownloadOutcome` enum (`SUCCESS / RETRYABLE_FAILURE / TERMINAL_FAILURE`) — `MediaDownloader.attempt_download` adapts to the legacy `bool` at its boundary for now.
- `src/bunkr_utils.py` — scrapes the public status page and owns the module-level `_status_cache`. Cache is keyed on `network.status_page` so concurrent jobs with distinct overrides maintain isolated caches. Failed downloads group by subdomain and re-check status via `refresh_server_status(subdomain, bunkr_status, network=…)` before final retries. Prefer `get_bunkr_status_cached(network)` in new code.

### Structured maintenance events
Two signals feed maintenance handling: the status page (`bunkr_utils`) and the item page itself (`api_utils.detect_item_page_maintenance`, matching Bunkr's "Download unavailable ... maintenance" notice on an HTTP 200 page). Both route through `update_maintenance` + `file_utils.log_maintenance_event`, and both use the `MAINTENANCE_BACKOFF_DELAYS_SECONDS` knob for `backoff` waits. Fixtures for the item-page shapes live in `tests/fixtures/`.

When surfacing a maintenance condition, call `live_manager.update_maintenance(subdomain=, status=, affected_files_count=, event=, details=)`. On the web side this emits both a `log` envelope *and* a structured `maintenance_detected` envelope with real fields; the CLI collapses to `update_log`. **Don't** use `update_log(event="Maintenance detected", …)` — the old regex-parser that recovered the subdomain from the formatted log string is gone.

### Event envelope contract (web layer)
Every message published through `JobEventBroker.publish` — whether delivered over `/ws/jobs/{job_id}` or `/api/downloads/{job_id}/events?since=N` — is stamped with:

- `event_id`: strictly monotonic int per job, starts at 1, assigned by the broker under a threading lock
- `ts`: ISO-8601 UTC timestamp, assigned once at broadcast time
- `type`: `log | task_created | task_updated | overall | status | maintenance_detected`
- plus type-specific fields

`frontend/src/lib/events.ts` is the TypeScript mirror of this contract; change both sides together.

Cursor semantics:
- `since=N` means `event_id > N`, not positional.
- The WS stream's **first frame is always `{type: "hello", next_id, next_index, ts}`** where `next_id` is the **last broadcast** `event_id` (`broker.last_event_id`), not the id that will be assigned next. A reconnecting client echoes it as `?since=` on one HTTP backfill and picks up from the first unseen event. Sending `next_event_id` instead would skip one envelope per reconnect — the code comments spell this out; don't "simplify" it.
- `/events` returns `{events, next_id, next_index}`; `next_index` is a legacy alias of `next_id` still sent for compatibility.
- The per-job buffer is a bounded `deque` (`JOB_EVENT_RETENTION`, default 2000). If `since` is below the oldest retained id, `/events` returns **410 Gone** with `{oldest_event_id, next_id}` and the client must reset its view rather than continue with a gap.
- Clients dedup on `event_id` and never maintain their own cursor — advance only from server-supplied `next_id` / `hello.next_id`.

### Broker loop binding
`JobEventBroker` is loop-bound lazily via `bind(loop)`, called eagerly from `Job.__post_init__` (wrapped in try/except so sync construction for tests still works) and re-asserted at the top of `_run_download_job`. Do not call `asyncio.get_running_loop()` inside `__init__` of anything that a dataclass `default_factory` will build.

### Web layer specifics (`src/web/app.py`)
- `JobStore` holds `Job` objects in-memory (no DB). Jobs are lost on restart; the UI copes via `session.log` + the **WebSocket + polling hybrid**. A background reaper (`_job_reaper`, started in the lifespan) evicts terminal jobs older than `JOB_TTL_HOURS` every `JOB_REAPER_INTERVAL_SECONDS`. Bounds are tested in `tests/unit/test_memory_bounds.py`.
- **Auth:** when `API_ACCESS_TOKEN` is set, `require_auth` demands `Authorization: Bearer <token>` on every `/api/*` route and `_authorize_websocket` demands `?token=<token>` on `/ws/*` (WS is accepted then closed with code 4401; unknown job closes with 4404). Unset means unauthenticated with a startup warning.
- **Path sandbox:** `custom_path` and `/api/directories?basePath` must resolve under `ALLOWED_DOWNLOAD_ROOT` (default `<cwd>/Downloads`), else HTTP 422. `/` disables it.
- **CORS:** `ALLOWED_ORIGINS` (comma list) wins over `ALLOWED_ORIGIN_REGEX` (default matches localhost/127.0.0.1 on any port).
- Security behaviour is pinned by `tests/integration/test_web_security.py`; job lifecycle by `tests/integration/test_web_job_flow.py`.
- **Update checker:** `src/web/update_check.py` backs `GET /api/update-check`. It fetches the latest GitHub release at most once per `UPDATE_CHECK_TTL_SECONDS` (6h) into a module-level cache — same pattern as `_status_cache` — compares semver server-side, and returns "no update" on any GitHub failure so the UI never errors. Always on, web only. Design spec: `docs/superpowers/specs/2026-06-03-update-available-checker-design.md`.
- `APP_VERSION` resolves per the "Version gotcha" above; `/api/meta` exposes it to the badge.
- The built frontend is served as static files from `frontend/dist` via the `asynccontextmanager` lifespan; `docker build` runs the Vite build in a `node:20-alpine` stage pinned to `$BUILDPLATFORM` (so multi-arch releases don't rebuild the bundle under QEMU) and copies the bundle into the Python image.
- `docker-compose.yml` currently forwards only `API_*`, `SESSION_LOG_PATH`, `STATUS_*` and `MAINTENANCE_RETRY_STRATEGY`. The PR2/auth/signing knobs above are documented in the README but **not** in compose; add them there if you want them settable from `.env` in a container.

### Frontend (`frontend/`)
React 18 + TypeScript + Chakra UI 2 + Zustand, built by Vite 7. Entry `src/main.tsx` → `src/App.tsx`. Layout:

- `lib/events.ts` — wire types (see contract above). `lib/api.ts` — axios client. `lib/ws-url.ts` — builds the WS URL (honours `VITE_WS_BASE_URL`). Note the frontend does **not** send `API_ACCESS_TOKEN` on `/api` or `?token=` on `/ws` today, so enabling the token breaks the bundled UI until that lands.
- `lib/store.ts` — the single Zustand store for the job view. Tasks live in a `Map` mutated in place and bumped once per `applyEvents` batch; rows subscribe to their own slice so a 200-file album doesn't re-render everything on every progress tick. Keep that pattern when adding state.
- `lib/connection.ts` — `JobConnection`, the deterministic WS-over-polling state machine. Invariants: exactly one of WS / poll is active at a time; the cursor advances only from server-stamped ids; every envelope passes through a `Set<number>` dedup (LRU-capped); a 410 from `/events` resets the whole view; after 5 failed WS attempts (exp. backoff, 15s cap) it falls back to 2s polling and re-tries WS every ~60s. Do not add a second code path that also feeds the store.
- `hooks/` — `useActiveJob`, `usePersistentState` (localStorage), `useThemePreference`.
- `components/` — `shell/` (AppShell, TopBar, ConnectionIndicator), `download/` (form, overall progress, task list/rows, directory picker), `logs/LogPane`, `settings/SettingsPanel`, `primitives/` (Surface, GlassProgress, StatusPill).
- `theme/` — OKLCH token set (`tokens.ts`), `ThemeProvider` with Auto/Light/Dark, `globals.css`. CSS modules under `styles/`.

`vite.config.js` proxies `/api` and `/ws` to `VITE_API_PROXY` (default `http://localhost:8000`). No router.

## Conventions

- **Conventional Commits are load-bearing** (not just style) — they drive semantic-release version bumps. `feat:` → minor, `fix:` → patch, `BREAKING CHANGE:` → major.
- Follow the **branch → PR → review → resolve → merge** loop for every commit set. Each PR is rebased on `main` before pushing so the reviewer sees a clean diff.
- Design docs for non-trivial features live in `docs/superpowers/specs/<date>-<slug>-design.md`.
- **Never stage local tooling artifacts:** `.remember/`, `.playwright-mcp/`, `supertool`, `pr3-*.png` screenshots. Use `git add -u` + explicit paths rather than `git add .`.
- `.gitignore` carries Python-artifact globs `lib/` and `logs/` that match *any* directory of that name, so `frontend/src/lib/` and `frontend/src/components/logs/` are rescued with `!` negations at the bottom. A new frontend directory named `lib`, `logs`, `build`, `dist`, `downloads`, etc. needs the same negation or it silently won't be tracked.
- `session.log` at `SESSION_LOG_PATH` persists failed URLs for manual retry; maintenance events are logged as `[MAINTENANCE] timestamp | subdomain | status | url`.
- Downloads default to `./Downloads/<album_name>-<album_id>/`; `--custom-path /foo` produces `/foo/Downloads/...` (the `Downloads` subfolder is appended by `create_download_directory`).
- The project targets Python ≥ 3.10. Type hints use `from __future__ import annotations` throughout.
- When writing tests that bind a `JobEventBroker` outside a running event loop: call `broker.bind(asyncio.get_running_loop())` inside the coroutine before `publish`. Tests that use `FastAPI TestClient` already get a running loop inside the `with TestClient(…) as client:` block.
