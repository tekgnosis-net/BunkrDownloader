"""FastAPI entrypoint that mirrors the CLI downloader for the web dashboard."""

from __future__ import annotations

import asyncio
import logging
import os
from argparse import Namespace
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, AnyHttpUrl

from downloader import validate_and_download
from src import __version__ as __app_version__
from src.bunkr_utils import get_bunkr_status
from src.config import MAX_WORKERS, get_network_settings, update_network_settings

_env_version = os.getenv("APP_VERSION", "")
if _env_version and _env_version.lower() != "latest":
    APP_VERSION = _env_version
else:
    APP_VERSION = __app_version__

logger = logging.getLogger(__name__)


def _format_duration(delta: timedelta) -> str:
    """Format a timedelta into the hh:mm:ss string used across the project."""
    total_seconds = int(delta.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02} hrs {minutes:02} mins {seconds:02} secs"


class NetworkOverrides(BaseModel):
    """Optional overrides for Bunkr networking endpoints."""

    status_page: AnyHttpUrl | None = Field(
        default=None,
        description="Status page URL override.",
    )
    api_endpoint: AnyHttpUrl | None = Field(
        default=None,
        description="API endpoint override.",
    )
    download_referer: AnyHttpUrl | None = Field(
        default=None,
        description="Referer header override.",
    )
    fallback_domain: str | None = Field(
        default=None,
        description="Fallback domain when retrying.",
    )
    user_agent: str | None = Field(
        default=None,
        max_length=512,
        description="Custom user agent for requests.",
    )


class DownloadRequest(BaseModel):
    """Payload used to kick off a download job via the HTTP API."""

    urls: list[AnyHttpUrl] = Field(..., min_length=1, description="List of Bunkr URLs.")
    include: list[str] = Field(default_factory=list)
    ignore: list[str] = Field(default_factory=list)
    custom_path: str | None = Field(default=None, description="Optional absolute base directory.")
    disable_disk_check: bool = Field(default=False, description="Skip the free disk space guard.")
    log_level: Literal["debug", "info", "warning", "error"] = Field(
        default="info",
        description="Verbosity applied to runtime logs for this job.",
    )
    max_workers: int = Field(
        default=MAX_WORKERS,
        ge=1,
        le=10,
        description="Maximum concurrent album downloads to run.",
    )
    network: NetworkOverrides | None = Field(
        default=None,
        description="Optional network configuration overrides applied before the job runs.",
    )


class DownloadResponse(BaseModel):
    """Identifier returned after a job has been scheduled."""

    job_id: str


class JobInfo(BaseModel):
    """Serializable representation of a tracked job."""

    job_id: str
    status: str
    created_at: datetime
    urls: list[str]
    error: str | None = None


class JobStatus(str, Enum):
    """Lifecycle states representing the status of a download job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobEventBroker:
    """Fan-out publisher that buffers job events for any active subscribers."""

    def __init__(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._events: list[dict[str, Any]] = []
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the asyncio event loop backing the broker."""

        return self._loop

    def _broadcast(self, event: dict[str, Any]) -> None:
        """Send an event to all subscribers and retain it for future replays."""

        self._events.append(event)
        for queue in list(self._subscribers):
            queue.put_nowait(event)

    def publish(self, event: dict[str, Any]) -> None:
        """Publish an event, marshaling to the main loop if needed."""
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            self._broadcast(event)
        else:
            self._loop.call_soon_threadsafe(self._broadcast, event)

    def get_events(self, start_index: int = 0) -> list[dict[str, Any]]:
        """Return a slice of the buffered events starting from the requested index."""
        if start_index <= 0:
            return list(self._events)
        return self._events[start_index:]

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Yield past and live events to a subscriber."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        for event in self._events:
            await queue.put(event)

        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)


class WebLiveManager:  # pylint: disable=too-many-instance-attributes
    """Adapter that mirrors the CLI LiveManager API for the web frontend."""

    def __init__(self, broker: JobEventBroker, log_level: str = "info") -> None:
        """Initialise the manager with an event broker used for notifications."""

        self._broker = broker
        self._loop = broker.loop
        self.live = nullcontext()
        self._next_task_id = 0
        self._overall = {"description": None, "total": 0, "completed": 0}
        self._tasks: dict[int, dict[str, Any]] = {}
        self._started_at = datetime.now(timezone.utc)
        self._log_level = log_level.lower()
        # Mirror the CLI boot message so behaviour stays consistent.
        self.update_log(event="Script started", details="The script has started execution.")
        self.update_log(
            event="Log level",
            details=f"Using {self._log_level.upper()} verbosity.",
        )

    def add_overall_task(self, description: str, num_tasks: int) -> None:
        """Publish an overall task describing the total work units expected."""

        def _impl() -> None:
            self._overall.update({
                "description": description,
                "total": num_tasks,
                "completed": 0,
            })
            self._broker.publish({
                "type": "overall",
                "description": description,
                "total": num_tasks,
                "completed": 0,
            })

        self._run_in_loop(_impl)

    def add_task(self, current_task: int = 0, total: int = 100) -> int:
        """Create and register a new task, returning its identifier."""

        label_total = self._overall["total"] or total
        task_id = self._next_task_id
        self._next_task_id += 1
        task = {
            "id": task_id,
            "label": f"File {current_task + 1}/{label_total}",
            "completed": 0.0,
            "visible": True,
            "finished": False,
        }
        self._tasks[task_id] = task
        self._broker.publish({"type": "task_created", "task": self._task_payload(task)})
        return task_id

    def update_task(
        self,
        task_id: int,
        completed: int | None = None,
        advance: int = 0,
        *,
        visible: bool = True,
    ) -> None:
        """Update an existing task's completion percentage and visibility."""

        def _impl() -> None:
            task = self._tasks.get(task_id)
            if task is None:
                return

            if completed is not None:
                task["completed"] = float(completed)
            elif advance:
                task["completed"] = min(100.0, task["completed"] + float(advance))

            task["visible"] = visible

            if task["completed"] >= 100.0 and not task["finished"]:
                task["finished"] = True
                if self._overall["total"]:
                    self._overall["completed"] = min(
                        self._overall["total"],
                        self._overall["completed"] + 1,
                    )
                    self._broker.publish({
                        "type": "overall",
                        "description": self._overall["description"],
                        "total": self._overall["total"],
                        "completed": self._overall["completed"],
                    })

            self._broker.publish({"type": "task_updated", "task": self._task_payload(task)})

        self._run_in_loop(_impl)

    def update_log(self, *, event: str, details: str) -> None:
        """Append a log entry to the job timeline and broadcast it."""

        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "type": "log",
            "event": event,
            "details": details,
            "timestamp": timestamp,
        }
        self._run_in_loop(self._broker.publish, payload)

    def log_debug(self, *, event: str, details: str) -> None:
        """Emit a log entry only when the current log level enables debug output."""

        if self._log_level == "debug":
            self.update_log(event=event, details=details)

    def start(self) -> None:  # noqa: D401 kept for API parity
        """Start hook kept for compatibility."""

    def stop(self) -> None:
        """Emit the closing log, including elapsed time, for the job."""

        def _impl() -> None:
            duration = datetime.now(timezone.utc) - self._started_at
            self._broker.publish({
                "type": "log",
                "event": "Script ended",
                "details": (
                    "The script has finished execution. "
                    f"Execution time: {_format_duration(duration)}"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        self._run_in_loop(_impl)

    def _task_payload(self, task: dict[str, Any]) -> dict[str, Any]:
        """Normalise the internal task dictionary for outgoing events."""

        return {
            "id": task["id"],
            "label": task["label"],
            "completed": task["completed"],
            "visible": task["visible"],
        }

    def _run_in_loop(self, callback: Callable[..., None], *args: Any) -> None:
        """Execute a callback in the manager loop, deferring if on another thread."""

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            callback(*args)
        else:
            self._loop.call_soon_threadsafe(callback, *args)


@dataclass(slots=True)
class Job:  # pylint: disable=too-many-instance-attributes
    """Tracked download job with runtime metadata and async task handles."""

    job_id: str
    request: DownloadRequest
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_broker: JobEventBroker = field(default_factory=JobEventBroker)
    manager: WebLiveManager | None = None
    task: asyncio.Task[None] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.manager is None:
            self.manager = WebLiveManager(self.event_broker, log_level=self.request.log_level)

    def as_dict(self) -> dict[str, Any]:
        """Return serialisable job data for API responses."""

        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "urls": [str(url) for url in self.request.urls],
            "error": self.error,
        }


class JobStore:
    """In-memory registry for active and completed jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def add(self, job: Job) -> None:
        """Store a job entry, ensuring writes happen sequentially."""

        async with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> Job | None:
        """Fetch a job by identifier, returning None when missing."""

        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        """Return a snapshot of all jobs currently tracked."""

        return list(self._jobs.values())


job_store = JobStore()


def _status_event(status: JobStatus, message: str | None = None) -> dict[str, Any]:
    """Construct a status event payload for subscribers."""

    payload = {
        "type": "status",
        "status": status.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if message:
        payload["message"] = message
    return payload


def _build_namespace(url: str, request: DownloadRequest) -> Namespace:
    """Build a CLI-like namespace from an incoming HTTP download request."""

    include = request.include or None
    ignore = request.ignore or None
    return Namespace(
        url=url,
        include=include,
        ignore=ignore,
        custom_path=request.custom_path,
        disable_ui=True,
        disable_disk_check=request.disable_disk_check,
        log_level=request.log_level,
        max_workers=request.max_workers,
        status_page=request.network.status_page if request.network else None,
        bunkr_api=request.network.api_endpoint if request.network else None,
        download_referer=request.network.download_referer if request.network else None,
        user_agent=request.network.user_agent if request.network else None,
        fallback_domain=request.network.fallback_domain if request.network else None,
    )


async def _run_download_job(job: Job) -> None:
    """Execute the download flow while emitting updates through the live manager."""

    assert job.manager is not None
    manager = job.manager

    job.status = JobStatus.RUNNING
    job.event_broker.publish(_status_event(JobStatus.RUNNING))

    try:
        if job.request.network:
            update_network_settings(
                status_page=job.request.network.status_page,
                api_endpoint=job.request.network.api_endpoint,
                download_referer=job.request.network.download_referer,
                user_agent=job.request.network.user_agent,
                fallback_domain=job.request.network.fallback_domain,
            )
        bunkr_status = await asyncio.to_thread(get_bunkr_status)
        manager.log_debug(
            event="Debug",
            details=f"Fetched bunkr status for {len(bunkr_status)} hosts",
        )
        for index, url in enumerate(job.request.urls, start=1):
            if len(job.request.urls) > 1:
                manager.update_log(
                    event="Processing URL",
                    details=f"{index}/{len(job.request.urls)}: {url}",
                )
            manager.log_debug(event="Debug", details=f"Starting download for {url}")
            args = _build_namespace(str(url), job.request)
            await validate_and_download(bunkr_status, str(url), manager, args=args)
            manager.log_debug(event="Debug", details=f"Completed download for {url}")

        manager.stop()
        job.status = JobStatus.COMPLETED
        job.event_broker.publish(_status_event(JobStatus.COMPLETED))

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception("Download job %s failed", job.job_id)
        job.status = JobStatus.FAILED
        job.error = str(exc)
        manager.update_log(event="Download failed", details=str(exc))
        manager.stop()
        job.event_broker.publish(_status_event(JobStatus.FAILED, str(exc)))


app = FastAPI(title="BunkrDownloader API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def ensure_frontend() -> None:
    """Mount the compiled frontend bundle if available."""

    dist_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=dist_path, html=True), name="frontend")


@app.get("/api/settings/defaults")
async def get_settings_defaults() -> dict[str, dict[str, str]]:
    """Return default settings so the frontend can mirror server configuration."""

    return {"network": get_network_settings()}


@app.post("/api/downloads", response_model=DownloadResponse)
async def start_download(request: DownloadRequest) -> DownloadResponse:
    """Schedule a new download job and return its identifier."""

    job = Job(job_id=uuid4().hex, request=request)
    await job_store.add(job)
    job.event_broker.publish(_status_event(JobStatus.PENDING))
    job.task = asyncio.create_task(_run_download_job(job))
    return DownloadResponse(job_id=job.job_id)


@app.get("/api/downloads", response_model=list[JobInfo])
async def list_downloads() -> list[JobInfo]:
    """Return metadata for each tracked download job."""

    return [JobInfo(**job.as_dict()) for job in job_store.list_jobs()]


@app.get("/api/downloads/{job_id}", response_model=JobInfo)
async def get_download(job_id: str) -> JobInfo:
    """Return the current state of a job by identifier."""

    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobInfo(**job.as_dict())


@app.get("/api/downloads/{job_id}/events")
async def get_download_events(job_id: str, since: int = Query(0, ge=0)) -> dict[str, Any]:
    """Fetch buffered events for a job starting at the requested index."""

    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    events = job.event_broker.get_events(start_index=since)
    next_index = since + len(events)
    return {"events": events, "next_index": next_index}


@app.get("/api/directories")
async def list_directories(base_path: str | None = Query(None, alias="basePath")) -> dict[str, Any]:
    """Return up to fifty sub-directories for the requested path."""

    path = Path(base_path).expanduser() if base_path else Path.cwd()
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:  # noqa: PERF203 path errors bubble up cleanly
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    entries = []
    for entry in resolved.iterdir():
        if entry.is_dir():
            entries.append(str(entry))
        if len(entries) >= 50:
            break

    return {"path": str(resolved), "directories": sorted(entries)}


@app.websocket("/ws/jobs/{job_id}")
async def job_updates(websocket: WebSocket, job_id: str) -> None:
    """Stream job updates to the caller via WebSocket."""

    job = job_store.get(job_id)
    if job is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    try:
        async for event in job.event_broker.subscribe():
            await websocket.send_json(event)
    except WebSocketDisconnect:
        return


class MetaResponse(BaseModel):
    """Response describing runtime metadata such as version information."""

    version: str


@app.get("/api/meta", response_model=MetaResponse)
async def read_meta() -> MetaResponse:
    """Expose runtime metadata for the frontend shell."""

    return MetaResponse(version=APP_VERSION)
