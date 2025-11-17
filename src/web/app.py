from __future__ import annotations

import asyncio
import logging
from argparse import Namespace
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, AnyHttpUrl

from downloader import validate_and_download
from src.bunkr_utils import get_bunkr_status

logger = logging.getLogger(__name__)


def _format_duration(delta: timedelta) -> str:
    """Format a timedelta into the hh:mm:ss string used across the project."""
    total_seconds = int(delta.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02} hrs {minutes:02} mins {seconds:02} secs"


class DownloadRequest(BaseModel):
    """Payload used to kick off a download job via the HTTP API."""

    urls: list[AnyHttpUrl] = Field(..., min_length=1, description="List of Bunkr URLs.")
    include: list[str] = Field(default_factory=list)
    ignore: list[str] = Field(default_factory=list)
    custom_path: str | None = Field(default=None, description="Optional absolute base directory.")
    disable_disk_check: bool = Field(default=False, description="Skip the free disk space guard.")


class DownloadResponse(BaseModel):
    job_id: str


class JobInfo(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    urls: list[str]
    error: str | None = None


class JobStatus(str, Enum):
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
        return self._loop

    def _broadcast(self, event: dict[str, Any]) -> None:
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


class WebLiveManager:
    """Adapter that mirrors the CLI LiveManager API for the web frontend."""

    def __init__(self, broker: JobEventBroker) -> None:
        self._broker = broker
        self._loop = broker.loop
        self.live = nullcontext()
        self._next_task_id = 0
        self._overall = {"description": None, "total": 0, "completed": 0}
        self._tasks: dict[int, dict[str, Any]] = {}
        self._started_at = datetime.now(timezone.utc)
        # Mirror the CLI boot message so behaviour stays consistent.
        self.update_log(event="Script started", details="The script has started execution.")

    def add_overall_task(self, description: str, num_tasks: int) -> None:
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
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "type": "log",
            "event": event,
            "details": details,
            "timestamp": timestamp,
        }
        self._run_in_loop(self._broker.publish, payload)

    def start(self) -> None:  # noqa: D401 kept for API parity
        """Start hook kept for compatibility."""

    def stop(self) -> None:
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
        return {
            "id": task["id"],
            "label": task["label"],
            "completed": task["completed"],
            "visible": task["visible"],
        }

    def _run_in_loop(self, callback: Callable[..., None], *args: Any) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            callback(*args)
        else:
            self._loop.call_soon_threadsafe(callback, *args)


@dataclass(slots=True)
class Job:
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
            self.manager = WebLiveManager(self.event_broker)

    def as_dict(self) -> dict[str, Any]:
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
        async with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        return list(self._jobs.values())


job_store = JobStore()


def _status_event(status: JobStatus, message: str | None = None) -> dict[str, Any]:
    payload = {
        "type": "status",
        "status": status.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if message:
        payload["message"] = message
    return payload


def _build_namespace(url: str, request: DownloadRequest) -> Namespace:
    include = request.include or None
    ignore = request.ignore or None
    return Namespace(
        url=url,
        include=include,
        ignore=ignore,
        custom_path=request.custom_path,
        disable_ui=True,
        disable_disk_check=request.disable_disk_check,
    )


async def _run_download_job(job: Job) -> None:
    assert job.manager is not None
    manager = job.manager

    job.status = JobStatus.RUNNING
    job.event_broker.publish(_status_event(JobStatus.RUNNING))

    try:
        bunkr_status = await asyncio.to_thread(get_bunkr_status)
        for index, url in enumerate(job.request.urls, start=1):
            if len(job.request.urls) > 1:
                manager.update_log(
                    event="Processing URL",
                    details=f"{index}/{len(job.request.urls)}: {url}",
                )
            args = _build_namespace(str(url), job.request)
            await validate_and_download(bunkr_status, str(url), manager, args=args)

        manager.stop()
        job.status = JobStatus.COMPLETED
        job.event_broker.publish(_status_event(JobStatus.COMPLETED))

    except Exception as exc:  # noqa: BLE001 propagate a structured error to the UI
        logger.exception("Download job %s failed", job.job_id)
        job.status = JobStatus.FAILED
        job.error = str(exc)
        manager.update_log(event="Download failed", details=str(exc))
        manager.stop()
        job.event_broker.publish(_status_event(JobStatus.FAILED, str(exc)))


app = FastAPI(title="BunkrDownloader API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def ensure_frontend() -> None:
    dist_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=dist_path, html=True), name="frontend")


@app.post("/api/downloads", response_model=DownloadResponse)
async def start_download(request: DownloadRequest) -> DownloadResponse:
    job = Job(job_id=uuid4().hex, request=request)
    await job_store.add(job)
    job.event_broker.publish(_status_event(JobStatus.PENDING))
    job.task = asyncio.create_task(_run_download_job(job))
    return DownloadResponse(job_id=job.job_id)


@app.get("/api/downloads", response_model=list[JobInfo])
async def list_downloads() -> list[JobInfo]:
    return [JobInfo(**job.as_dict()) for job in job_store.list_jobs()]


@app.get("/api/downloads/{job_id}", response_model=JobInfo)
async def get_download(job_id: str) -> JobInfo:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobInfo(**job.as_dict())


@app.get("/api/downloads/{job_id}/events")
async def get_download_events(job_id: str, since: int = Query(0, ge=0)) -> dict[str, Any]:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    events = job.event_broker.get_events(start_index=since)
    next_index = since + len(events)
    return {"events": events, "next_index": next_index}


@app.get("/api/directories")
async def list_directories(base_path: str | None = Query(None, alias="basePath")) -> dict[str, Any]:
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

