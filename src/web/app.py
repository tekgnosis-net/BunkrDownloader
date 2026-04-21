"""FastAPI entrypoint that mirrors the CLI downloader for the web dashboard."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from argparse import Namespace
from contextlib import asynccontextmanager, nullcontext
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
from src.bunkr_utils import get_bunkr_status_cached
from src.config import MAX_WORKERS, build_network_context, get_network_settings

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
    CANCELLED = "cancelled"


class JobEventBroker:
    """Fan-out publisher that buffers job events for any active subscribers.

    Each published envelope is stamped with a monotonically increasing
    ``event_id`` (per job, starting at 1) and an ISO-8601 ``ts``. The same
    envelope object is delivered through the WebSocket stream and the
    ``/events`` polling fallback, so the client can dedup on ``event_id``
    alone. The broker is loop-bound on first use rather than at construction
    so dataclass ``default_factory`` can safely build one outside an async
    context (e.g. in unit tests).
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._events: list[dict[str, Any]] = []
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._id_lock = threading.Lock()
        self._event_seq = 0

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """Attach the broker to the event loop that owns its subscribers.

        Safe to call repeatedly with the same loop. Idempotent to preserve
        the ``Job.__post_init__`` → ``_run_download_job`` two-phase bind.
        """

        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("JobEventBroker is already bound to a different loop")
        self._loop = loop

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the asyncio event loop backing the broker."""

        if self._loop is None:
            raise RuntimeError(
                "JobEventBroker used before bind(loop) — construct Job inside "
                "an async context or call bind() explicitly",
            )
        return self._loop

    def _broadcast(self, event: dict[str, Any]) -> None:
        """Stamp the envelope, retain it for replays, and fan out live."""

        with self._id_lock:
            self._event_seq += 1
            event["event_id"] = self._event_seq
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        self._events.append(event)
        for queue in list(self._subscribers):
            queue.put_nowait(event)

    @property
    def next_event_id(self) -> int:
        """Return the ``event_id`` that will be assigned to the next publish."""

        return self._event_seq + 1

    @property
    def last_event_id(self) -> int:
        """Return the highest ``event_id`` published so far (0 if none).

        This is the value a client passes as ``since`` on its next backfill
        request — ``/events`` returns envelopes with ``event_id > since``, so
        ``since = last_event_id`` yields only envelopes published afterwards.
        Kept aligned with the ``next_id`` field that ``/events`` emits, so the
        WebSocket ``hello`` frame and the HTTP polling endpoint agree on what
        the cursor means.
        """

        return self._event_seq

    def publish(self, event: dict[str, Any]) -> None:
        """Publish an event, marshaling to the bound loop when called off-thread."""

        # Access the bound loop through the property so unbound brokers raise
        # an explicit RuntimeError instead of silently matching the ``None``
        # from a sync context and discarding events into _broadcast without a
        # subscriber fan-out loop.
        bound_loop = self.loop
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is bound_loop:
            self._broadcast(event)
        else:
            bound_loop.call_soon_threadsafe(self._broadcast, event)

    def get_events(self, since: int = 0) -> list[dict[str, Any]]:
        """Return envelopes with ``event_id > since``.

        Positional semantics (by list index) were brittle once the broker is
        allowed to discard older events; ``event_id`` is authoritative.
        """

        if since <= 0:
            return list(self._events)
        return [event for event in self._events if event.get("event_id", 0) > since]

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Yield past and live events to a subscriber.

        Snapshot-then-register is atomic on the broker loop because
        :meth:`_broadcast` never awaits — no event can land between taking the
        snapshot and adding the queue to ``_subscribers``, so no event is
        dropped, and none is delivered twice.
        """

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        snapshot = list(self._events)
        self._subscribers.add(queue)
        try:
            for event in snapshot:
                yield event
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)


class WebLiveManager:  # pylint: disable=too-many-instance-attributes
    """Adapter that mirrors the CLI LiveManager API for the web frontend."""

    def __init__(self, broker: JobEventBroker, log_level: str = "info") -> None:
        """Initialise the manager with an event broker used for notifications.

        The broker's loop is looked up lazily via :meth:`_loop`. This allows
        the manager to be constructed before the broker has been bound — the
        two-phase pattern used by :class:`Job` when it is instantiated inside
        a request handler (bound early) vs a unit test (bound by
        :func:`_run_download_job` at start time).
        """

        self._broker = broker
        self.live = nullcontext()
        self._task_id_lock = threading.Lock()
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
        """Reserve a task id and publish its creation on the broker loop.

        ``add_task`` is called from worker threads spawned by
        :func:`asyncio.to_thread`, so the id counter is guarded by a
        :class:`threading.Lock`. The task's presence in ``self._tasks`` is
        only realised once the :meth:`_run_in_loop` closure runs; a bounded
        retry in :meth:`update_task` tolerates the small window where an
        update lands before the registration closure has fired.
        """

        label_total = self._overall["total"] or total
        with self._task_id_lock:
            task_id = self._next_task_id
            self._next_task_id += 1
        task = {
            "id": task_id,
            "label": f"File {current_task + 1}/{label_total}",
            "completed": 0.0,
            "visible": True,
            "finished": False,
        }

        def _impl() -> None:
            self._tasks[task_id] = task
            self._broker.publish(
                {"type": "task_created", "task": self._task_payload(task)},
            )

        self._run_in_loop(_impl)
        return task_id

    def update_task(
        self,
        task_id: int,
        completed: int | None = None,
        advance: int = 0,
        *,
        visible: bool = True,
    ) -> None:
        """Update an existing task's completion percentage and visibility.

        The update is silently no-ops when nothing changed, preventing
        ``task_updated`` from spamming the wire with identical state. If the
        corresponding :meth:`add_task` closure hasn't landed on the broker
        loop yet, the update is rescheduled once via ``call_soon``.
        """

        retry_flag = {"retried": False}

        def _impl() -> None:
            task = self._tasks.get(task_id)
            if task is None:
                if retry_flag["retried"]:
                    return
                retry_flag["retried"] = True
                self._broker.loop.call_soon(_impl)
                return

            before = (task["completed"], task["visible"], task["finished"])

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

            after = (task["completed"], task["visible"], task["finished"])
            if before == after:
                return

            self._broker.publish(
                {"type": "task_updated", "task": self._task_payload(task)},
            )

        self._run_in_loop(_impl)

    def update_log(self, *, event: str, details: str) -> None:
        """Append a log entry to the job timeline and broadcast it."""

        payload = {"type": "log", "event": event, "details": details}
        self._run_in_loop(self._broker.publish, payload)

    def log_debug(self, *, event: str, details: str) -> None:
        """Emit a log entry only when the current log level enables debug output."""

        if self._log_level == "debug":
            self.update_log(event=event, details=details)

    def update_maintenance(  # pylint: disable=too-many-arguments
        self,
        *,
        subdomain: str,
        status: str,
        affected_files_count: int,
        event: str,
        details: str,
    ) -> None:
        """Emit both a structured ``maintenance_detected`` envelope and a log.

        The upstream callers already know the subdomain, maintenance status
        and affected file count — passing them explicitly replaces the old
        regex that tried to recover these values from the formatted log
        string itself.
        """

        maintenance_payload = {
            "type": "maintenance_detected",
            "subdomain": subdomain,
            "status": status,
            "affected_files_count": affected_files_count,
            "event": event,
            "details": details,
        }
        self._run_in_loop(self._broker.publish, maintenance_payload)
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
        """Execute a callback in the broker loop, deferring if on another thread."""

        loop = self._broker.loop
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is loop:
            callback(*args)
        else:
            loop.call_soon_threadsafe(callback, *args)


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
        # Binding the broker before the manager is constructed is load-bearing:
        # the manager's __init__ emits the startup log lines, which fan out
        # through the broker's loop. Jobs instantiated outside an async context
        # (e.g. in tests) can still construct the broker — they must bind it
        # themselves before creating the manager.
        try:
            self.event_broker.bind(asyncio.get_running_loop())
        except RuntimeError:
            pass
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

    if job.manager is None:
        raise RuntimeError(f"Job {job.job_id} has no live manager attached")
    manager = job.manager

    # Ensure the broker is bound to this loop even if Job() was constructed
    # outside an async context before the task was scheduled.
    job.event_broker.bind(asyncio.get_running_loop())

    job.status = JobStatus.RUNNING
    job.event_broker.publish(_status_event(JobStatus.RUNNING))

    try:
        # Build a per-job NetworkContext — no module-level mutation, so two
        # concurrent jobs with different overrides cannot interfere. The
        # equivalent namespace is also threaded through ``args`` below so
        # ``validate_and_download`` can reproduce the same context inside.
        job_args_preview = _build_namespace(str(job.request.urls[0]), job.request)
        job_network = build_network_context(job_args_preview)
        bunkr_status = await asyncio.to_thread(get_bunkr_status_cached, job_network)
        if not isinstance(bunkr_status, dict):
            logger.warning(
                "Bunkr status lookup returned %s; defaulting to empty mapping",
                type(bunkr_status),
            )
            bunkr_status = {}
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

    except asyncio.CancelledError as cancel_err:
        logger.info("Download job %s cancelled", job.job_id)
        job.status = JobStatus.CANCELLED
        job.error = "Cancelled by user"
        manager.update_log(event="Download cancelled", details="Cancelled by user request")
        manager.stop()
        job.event_broker.publish(_status_event(JobStatus.CANCELLED, "Cancelled by user"))
        raise cancel_err

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception("Download job %s failed", job.job_id)
        job.status = JobStatus.FAILED
        job.error = str(exc)
        manager.update_log(event="Download failed", details=str(exc))
        manager.stop()
        job.event_broker.publish(_status_event(JobStatus.FAILED, str(exc)))


@asynccontextmanager
async def _lifespan(app_instance: FastAPI):
    """Mount the compiled frontend bundle on startup if it's available."""

    dist_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist_path.exists():
        app_instance.mount(
            "/", StaticFiles(directory=dist_path, html=True), name="frontend",
        )
    yield


app = FastAPI(title="BunkrDownloader API", version=APP_VERSION, lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.post("/api/downloads/{job_id}/cancel")
async def cancel_download(job_id: str) -> dict[str, Any]:
    """Attempt to cancel a running download job."""

    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }:
        return {"status": job.status.value}

    if job.task is None:
        job.status = JobStatus.CANCELLED
        job.error = "Cancelled before start"
        if job.manager:
            job.manager.update_log(
                event="Download cancelled",
                details="Cancelled before the task started",
            )
            job.manager.stop()
        job.event_broker.publish(_status_event(JobStatus.CANCELLED, "Cancelled before start"))
        return {"status": job.status.value}

    job.task.cancel()
    try:
        await job.task
    except asyncio.CancelledError:
        pass

    return {"status": job.status.value}


@app.get("/api/downloads/{job_id}/events")
async def get_download_events(job_id: str, since: int = Query(0, ge=0)) -> dict[str, Any]:
    """Fetch buffered events for a job with ``event_id > since``.

    ``next_id`` is the cursor the client should pass on its next request.
    ``next_index`` is kept as an alias equal to ``next_id`` so the current
    frontend keeps working while the PR3 client migrates to ``next_id``.
    """

    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    events = job.event_broker.get_events(since=since)
    if events:
        next_id = max(event.get("event_id", since) for event in events)
    else:
        next_id = since
    return {"events": events, "next_id": next_id, "next_index": next_id}


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
    """Stream job updates to the caller via WebSocket.

    Sends a ``hello`` envelope first containing the broker's ``next_event_id``
    so the client knows the authoritative cursor position — if its local
    cursor is behind, the client can issue a single HTTP backfill against
    ``/api/downloads/{job_id}/events?since=<cursor>`` and resume the live
    stream with zero duplicate events.
    """

    job = job_store.get(job_id)
    if job is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    # Send the LAST broadcast event_id, not the next one. /events treats
    # ``since`` as "envelopes with event_id > since", so a client that
    # echoes this value on its next HTTP backfill picks up cleanly from
    # the first unseen event. Using ``next_event_id`` here would silently
    # skip one envelope on every reconnect.
    hello_cursor = job.event_broker.last_event_id
    hello_envelope = {
        "type": "hello",
        "next_id": hello_cursor,
        "next_index": hello_cursor,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await websocket.send_json(hello_envelope)
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
