"""Tests for PR2 memory hygiene: ring buffer, 410 Gone, job reaper."""

# pylint: disable=missing-function-docstring,protected-access,unused-argument
# pylint: disable=import-outside-toplevel,redefined-outer-name,reimported,unused-import
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.web.app import (
    Job,
    JobEventBroker,
    JobStatus,
    JobStore,
    _job_reaper,
)


@pytest.mark.asyncio
async def test_event_buffer_drops_oldest_at_retention_limit() -> None:
    """When the ring buffer is full, the oldest envelope is evicted first."""

    broker = JobEventBroker(retention=10)
    broker.bind(asyncio.get_running_loop())

    for i in range(25):
        broker.publish({"type": "log", "event": f"e{i}", "details": ""})

    retained = broker.get_events()
    assert len(retained) == 10
    # Monotonic ids are preserved even across pruning — the oldest id is 16.
    assert [e["event_id"] for e in retained] == list(range(16, 26))
    assert broker.oldest_event_id == 16
    assert broker.next_event_id == 26


def test_since_below_oldest_returns_410() -> None:
    """Clients with a cursor below the pruned floor get 410 Gone, not a silent gap.

    Uses :meth:`_broadcast` directly so the broker doesn't need a bound
    event loop for this scenario — the ``/events`` HTTP endpoint only reads
    ``_events`` and the ``oldest_event_id`` / ``next_event_id`` properties,
    none of which touch the loop. This keeps the test synchronous and
    deterministic without the cross-loop marshaling TestClient introduces.
    """

    from fastapi.testclient import TestClient
    from types import SimpleNamespace

    from src.web.app import JobEventBroker, app as fastapi_app, job_store

    job_store._jobs.clear()

    broker = JobEventBroker()
    for i in range(30):
        broker._broadcast({"type": "log", "event": f"fill{i}", "details": ""})
    while len(broker._events) > 10:
        broker._events.popleft()

    oldest = broker.oldest_event_id
    assert oldest is not None and oldest > 1

    # Slot the minimal ``event_broker`` surface the endpoint reads directly
    # into the store. Bypasses Job + WebLiveManager, which require a running
    # loop to construct.
    job_store._jobs["hand-seeded-410"] = SimpleNamespace(event_broker=broker)

    with TestClient(fastapi_app) as client:
        resp = client.get(
            "/api/downloads/hand-seeded-410/events", params={"since": 1},
        )

    assert resp.status_code == 410, resp.text
    body = resp.json()["detail"]
    assert body["error"] == "events pruned"
    assert body["oldest_event_id"] == oldest


@pytest.mark.asyncio
async def test_job_reaper_evicts_old_terminal_jobs() -> None:
    """Only terminal jobs older than the TTL are evicted."""

    store = JobStore()

    # Build a few jobs with known created_at + statuses.
    from src.web.app import DownloadRequest

    async def _seed(status: JobStatus, hours_old: int) -> Job:
        job = Job(
            job_id=f"job-{status.value}-{hours_old}",
            request=DownloadRequest(urls=["https://bunkr.test/a/x"]),
        )
        # Backdate the timestamp
        object.__setattr__(
            job,
            "created_at",
            datetime.now(timezone.utc) - timedelta(hours=hours_old),
        )
        job.status = status
        await store.add(job)
        return job

    fresh_running = await _seed(JobStatus.RUNNING, 99)  # never reaped (active)
    fresh_done = await _seed(JobStatus.COMPLETED, 1)    # too young
    stale_done = await _seed(JobStatus.COMPLETED, 48)   # reap
    stale_failed = await _seed(JobStatus.FAILED, 48)    # reap
    stale_cancelled = await _seed(JobStatus.CANCELLED, 48)  # reap

    removed = await store.reap(ttl_hours=24)

    assert set(removed) == {stale_done.job_id, stale_failed.job_id, stale_cancelled.job_id}
    remaining = {j.job_id for j in store.list_jobs()}
    assert fresh_running.job_id in remaining
    assert fresh_done.job_id in remaining
    assert stale_done.job_id not in remaining


@pytest.mark.asyncio
async def test_job_reaper_loop_cancels_cleanly() -> None:
    """The reaper background loop terminates on cancel without logging errors."""

    store = JobStore()
    task = asyncio.create_task(
        _job_reaper(store, ttl_hours=24, interval_seconds=3600),
    )
    # Give it one scheduling tick
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
