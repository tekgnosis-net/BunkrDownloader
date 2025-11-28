# BunkrDownloader

Rich CLI + web dashboard for grabbing albums and files from Bunkr with resilient retries, live progress, and container-ready deployment.

![Web dashboard screenshot](assets/WebUI.png)

## Table of Contents
- [BunkrDownloader](#bunkrdownloader)
  - [Table of Contents](#table-of-contents)
  - [Highlights](#highlights)
  - [Quick Start](#quick-start)
    - [With Docker Compose (recommended)](#with-docker-compose-recommended)
    - [Local runtime](#local-runtime)
  - [CLI Usage](#cli-usage)
  - [Web Dashboard](#web-dashboard)
  - [Configuration](#configuration)
  - [Architecture](#architecture)
  - [Development](#development)
  - [Contributing](#contributing)
  - [Automation](#automation)
  - [Support \& Issues](#support--issues)
  - [Forked credits](#forked-credits)
  - [License](#license)

## Highlights
- **Dual experience**: Python CLI (`downloader.py`, `main.py`) or a Chakra UI dashboard powered by FastAPI.
- **Realtime feedback**: Rich terminal UI and a websocket + polling hybrid on the web keep progress/logs alive, even after restarts.
- **Smart filtering**: Include/ignore rules, disk-space guard, filename sanitisation, and album pagination handled automatically.
- **Configurable storage**: Point downloads to any folder (CLI `--custom-path` or web directory picker) with existing files skipped safely.
- **Container friendly**: Multi-stage Docker image, docker-compose stack, and CI pipeline for publishing multi-arch images to GHCR.

## Quick Start

### With Docker Compose (recommended)
```bash
cd BunkrDownloader
cp .env.sample .env                     # customise API_PORT, DOWNLOADS_DIR, etc.
docker compose pull                     # grabs ghcr.io/tekgnosis-net/bunkrdownloader:${IMAGE_TAG:-latest}
docker compose up -d                    # start the FastAPI + web UI stack
```
By default the service listens on `http://localhost:8000`. Override the port or downloads path by editing `.env` (or exporting `API_PORT` / `DOWNLOADS_DIR` before `docker compose up`). Set `IMAGE_TAG` to a published semantic version (for example `1.2.3`) if you want to pin a specific release; otherwise `latest` is used. Use `docker compose logs -f bunkr` to watch progress and `docker compose down` when you're finished.

### Local runtime
```bash
# Backend
pip install -r requirements.txt
uvicorn src.web.app:app --reload

# Frontend (optional live dev server)
cd frontend
npm install
npm run dev
```
The Vite dev server proxies API/WebSocket traffic to `http://localhost:8000` by default. Run `npm run build` once to bake a production bundle served by FastAPI.

## CLI Usage
```bash
# Single URL
python3 downloader.py <bunkr_url> [--include term ...] [--ignore term ...] [--custom-path /path] [--disable-ui] [--disable-disk-check]

# Batch mode (URLs.txt)
python3 main.py [shared flags]
```
- `--include` downloads files containing any supplied substring.
- `--ignore` skips files containing any supplied substring.
- `--custom-path` points downloads to `<path>/Downloads`.
- `--disable-ui` swaps the Rich interface for plain logging (useful in notebooks/CI).

## Web Dashboard
- **Job launcher** – paste URLs, set filters, toggle the disk check, or choose a custom destination via the directory browser.
- **Progress panes** – overall progress + per-file stripes; tooltips explain each control and metric.
- **Live log** – chronological events, retries, and skips with full timestamps.
- **Resilient updates** – when a WebSocket drops (e.g. container restart) the UI polls `/api/downloads/{job}/events` until the socket reconnects.
- **Source shortcut** – in-app link to the GitHub repository for quick reference.
- **Version badge** – header shows the semantic version embedded in the running container image.

## Configuration
- `.env` (tracked example) controls container defaults: `API_HOST`, `API_PORT`, `DOWNLOADS_DIR`, plus Vite proxy hints (`VITE_*`).
- Web UI tooltips describe every form element; hover to see accepted formats and side effects.
- Downloads default to `Downloads/` in the working directory unless `custom_path` (CLI) or the directory picker overrides it.
- `session.log` persists problematic URLs so you can retry them later.

## Architecture
- `downloader.py` / `main.py` call `validate_and_download`, which builds a `SessionInfo` and streams progress via `LiveManager`.
- `src/web/app.py` wraps the same flow: `JobEventBroker` buffers events, `WebLiveManager` mirrors CLI progress/log calls, and FastAPI exposes REST + WebSocket endpoints.
- `src/crawlers/*` resolve album pagination, decrypt media URLs, and normalise filenames.
- `src/downloaders/*` handle concurrency, retries, and chunked writes through `download_utils.save_file_with_progress`; subdomain outages are tracked with `bunkr_utils`.
- `frontend/src/App.jsx` consumes `/api/downloads`, `/api/directories`, `/ws/jobs/{id}`, and the `/api/downloads/{id}/events` polling fallback for seamless updates.

## Development
- Python ≥ 3.10, Node ≥ 18 recommended.
- Activate the virtualenv and lint with `python -m pylint $(git ls-files '*.py')`; resolve any findings before committing.
- Run `python -m compileall src` and `npm run build` before opening a PR to catch syntax/bundle issues.
- `docker compose up --build` exercises the full stack locally using the tracked `.env`.
- Use `session.log` and the web log pane to inspect failed URLs or storage issues.

## Contributing
- Start with the guidelines in `CONTRIBUTING.md` for branching, linting, and smoke-test expectations.
- Prefer [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, etc.) so semantic-release can generate changelogs correctly.
- Include the manual checks you ran (lint, `compileall`, `npm run build`, CLI/Web smoke tests) in your pull request description.
- Keep your branch rebased on `main` and respond quickly to review feedback to keep the release pipeline flowing.

## Support & Issues
- Open a new issue from the repository’s **Issues → New issue** page; choose the **Bug report** template for defects or the **Feature request** template for enhancements.
- The templates collect environment details (OS, Python version, tool version) and walk you through logs, reproduction steps, and desired outcomes so maintainers can triage quickly.
- Always confirm you’re running the latest release from [GitHub Releases](https://github.com/tekgnosis-net/BunkrDownloader/releases) and search for duplicates before filing.
- Blank issues are disabled, so pick the template that’s closest to your situation and use the “Additional context” field to capture anything extra.

## Forked credits
This project is a fork of [Lysagxra/BunkrDownloader](https://github.com/Lysagxra/BunkrDownloader). However, it has been heavily refactored and modified for a web dashboard interface and other enhancements including dockerizing the application.

## License
MIT License © tekgnosis-net
