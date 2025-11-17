# Copilot Instructions for BunkrDownloader

## Architecture & Data Flow
- `downloader.py` (single URL) and `main.py` (batch via `URLs.txt`) both end up in `validate_and_download`, which builds a `SessionInfo` (args + Bunkr status + download path) and hands everything to `LiveManager`.
- `src/crawlers/` is responsible for resolving album pagination and decrypting links: `crawler_utils.get_download_info` calls `api_utils.get_api_response/decrypt_url` to turn a slug into a real download URL.
- `src/downloaders/album_downloader.py` fans out album items concurrently (bounded by `MAX_WORKERS`) and defers per-file work to `MediaDownloader`; blocking downloads always run in `asyncio.to_thread` so the event loop stays responsive.
- `MediaDownloader` owns retry logic, include/ignore filtering, and subdomain outage handling (via `bunkr_utils`). All file writes go through `download_utils.save_file_with_progress`, which expects a `LiveManager` task id.
- `src/managers/` keep the Rich-based UI in sync. If you add new long-running work, surface it through `LiveManager.add_task/update_task` so both TTY and `--disable-ui` flows continue to work.
- `src/web/app.py` exposes the same orchestration through FastAPI. `JobEventBroker` buffers events per job, `WebLiveManager` maps progress/log calls into JSON events (`status`, `overall`, `task_created`, `task_updated`, `log`), and `asyncio.create_task` drives each download job.
- `frontend/` is a Vite + Chakra UI dashboard that listens on `/ws/jobs/{id}` for those events and POSTs to `/api/downloads`. The FastAPI app serves the production build from `frontend/dist` once `npm run build` has run.

## Key Workflows
- Always create and activate a local virtual environment (`python3 -m venv .venv` then `source .venv/bin/activate`) before running Python commands.
- Install deps once inside the virtual environment with `pip install -r requirements.txt` (Python ≥3.10).
- Single URL: `python3 downloader.py <bunkr_url> [--ignore STR ... --include STR ... --custom-path /path --disable-ui --disable-disk-check]`. Album/file detection happens automatically through `url_utils.check_url_type`.
- Batch mode: populate `URLs.txt` (one URL per line) and run `python3 main.py [shared flags]`. The script clears `session.log` before starting and truncates `URLs.txt` afterward, so don’t rely on that file for history.
- Web UI: `uvicorn src.web.app:app --reload` serves the API and any built static assets. For live frontend work run `npm install` once then `npm run dev` (proxies to `http://localhost:8000`); ship builds with `npm run build`.
- Logs & errors: transient issues are shown in the Rich logger; anything that should survive UI refreshes must be appended with `file_utils.write_on_session_log`.
- Docker image bundles both layers: `docker build -t bunkrdownloader .` then `docker run -p 8000:8000 -v $PWD/Downloads:/app/Downloads bunkrdownloader` to persist downloads locally.
- Compose stack mirrors the same image: update `.env` (tracked) and run `docker compose up --build`; `API_PORT` controls the published port, `DOWNLOADS_DIR` sets the bind mount.

## Pre-commit Requirements
- Before staging or committing anything, run `python -m pylint $(git ls-files '*.py')` inside the activated virtualenv and resolve every reported issue—no commits or pushes are allowed while lint fails.
- Run the relevant local smoke tests for the area you touched (CLI runs, `python -m compileall src`, frontend build, etc.) and do not push until they succeed, so CI workflows stay green.

## Conventions & Integration Points
- Extend CLI options in `src/config.py` (`setup_parser`/`parse_arguments`) so both entrypoints stay aligned.
- Always fetch HTML with `general_utils.fetch_page`: it retries 403s by swapping to the `.cr` domain and writes bad URLs into `session.log`.
- When generating filenames or directories, run them through `file_utils.truncate_filename`, `remove_invalid_characters`, and `create_download_directory` to avoid OS-specific issues.
- Respect `SessionInfo.args.ignore/include` when adding new download paths; skipped files must log via `live_manager.update_log` and hide their progress task to keep the UI tidy.
- Network calls should re-use the shared `HEADERS`/`DOWNLOAD_HEADERS`. If you add another API integration, follow the pattern in `src/crawlers/api_utils.py` (wrap `requests` calls, log warnings, and return parsed JSON/plain values).
- Any new retry/backoff logic should mirror `MediaDownloader._retry_with_backoff` (exponential backoff + jitter) and propagate failures through the existing `failed_downloads` queue, so album retries still happen in a single sweep.
- Keep the web event contract in sync: add new message types in `WebLiveManager._broker.publish` and update the Chakra UI switch in `frontend/src/App.jsx` to handle them. Existing consumers expect percentage floats for `task.*` and incremental counts for `overall`.
- `/api/downloads/{id}/events` replays buffered events for the polling fallback; return shapes must stay identical to the WebSocket payloads so the UI can reuse `handleEvent`.
- `/api/directories` is the only filesystem-browsing endpoint; validate/sanitise paths there instead of in request handlers.

## Verification & Debugging Tips
- There is no formal test suite. Exercise changes by running `python3 downloader.py <sample_url>` or `python3 main.py` against a short list, ideally with `--disable-ui` inside notebooks/CI to avoid Rich rendering issues.
- Watch `session.log` for silent failures (disk space, bad slugs, offline subdomains) and keep the log format consistent so downstream tooling can parse it.
- When diagnosing slowdowns, remember that `MAX_WORKERS` in `src/config.py` controls album concurrency, and `download_utils.get_chunk_size` selects chunk sizes based on file size thresholds—tune these constants rather than inlining new heuristics.
- For the web stack, smoke-test with `npm run build` and `python -m compileall src`; both commands are fast and catch most integration errors before starting `uvicorn`.
- Frontend dependencies should stay on Vite ≥7 to pull patched `esbuild` (`npm audit` must be clean). If newer advisories appear, prefer pinning safe versions over `audit fix --force` upgrades.
