"""Regression tests for :class:`WebLiveManager` concurrency and dedup."""

from __future__ import annotations

import asyncio
import threading

import pytest

from src.web.app import JobEventBroker, WebLiveManager


@pytest.mark.asyncio
async def test_concurrent_add_task_yields_unique_ids() -> None:
    """Workers calling ``add_task`` from multiple threads get distinct ids.

    Regression guard for the read-modify-write race on ``_next_task_id`` that
    previously could hand out duplicate task ids under ``asyncio.to_thread``
    contention.
    """

    broker = JobEventBroker()
    broker.bind(asyncio.get_running_loop())
    mgr = WebLiveManager(broker)
    mgr.add_overall_task("album", 500)

    results: list[list[int]] = [[] for _ in range(8)]

    def worker(out: list[int], n: int) -> None:
        for i in range(n):
            out.append(mgr.add_task(current_task=i))

    threads = [threading.Thread(target=worker, args=(results[i], 50)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    all_ids = [x for sub in results for x in sub]
    assert len(set(all_ids)) == len(all_ids), "duplicate task ids"
    assert sorted(all_ids) == list(range(min(all_ids), max(all_ids) + 1))

    # Drain the call_soon_threadsafe queue so task_created envelopes land.
    for _ in range(10):
        await asyncio.sleep(0.01)

    created = [e for e in broker.get_events() if e.get("type") == "task_created"]
    assert len(created) == len(all_ids)


@pytest.mark.asyncio
async def test_update_task_dedupes_no_ops() -> None:
    """A re-send of the same ``(completed, visible)`` state must not republish."""

    broker = JobEventBroker()
    broker.bind(asyncio.get_running_loop())
    mgr = WebLiveManager(broker)
    mgr.add_overall_task("album", 1)
    task_id = mgr.add_task(current_task=0)

    # Let add_task's registration closure land.
    await asyncio.sleep(0.02)
    baseline = len(broker.get_events())

    mgr.update_task(task_id, completed=50)
    await asyncio.sleep(0.02)
    after_first = len(broker.get_events())
    assert after_first > baseline, "first update should publish"

    mgr.update_task(task_id, completed=50)
    await asyncio.sleep(0.02)
    after_dup = len(broker.get_events())
    assert after_dup == after_first, "identical update must not republish"


@pytest.mark.asyncio
async def test_update_task_retries_when_registration_pending() -> None:
    """An update enqueued before its add_task closure runs must not be dropped.

    The retry closure reschedules once via ``loop.call_soon``; one bounded
    retry is enough because ``add_task`` and ``update_task`` both serialise on
    the broker loop.
    """

    broker = JobEventBroker()
    broker.bind(asyncio.get_running_loop())
    mgr = WebLiveManager(broker)
    mgr.add_overall_task("album", 1)
    # Call add_task and update_task back-to-back synchronously — the update's
    # closure will fire before the add's ``_tasks`` write has landed.
    task_id = mgr.add_task(current_task=0)
    mgr.update_task(task_id, completed=25)

    # Give both closures (and the one re-schedule) time to land.
    for _ in range(5):
        await asyncio.sleep(0.01)

    updated = [e for e in broker.get_events() if e.get("type") == "task_updated"]
    assert updated, "update_task should land after the retry"
    assert updated[-1]["task"]["completed"] == 25.0


@pytest.mark.asyncio
async def test_update_maintenance_publishes_structured_envelope() -> None:
    """Structured maintenance events keep the subdomain / count fields intact."""

    broker = JobEventBroker()
    broker.bind(asyncio.get_running_loop())
    mgr = WebLiveManager(broker)

    mgr.update_maintenance(
        subdomain="Cdn13",
        status="Maintenance",
        affected_files_count=7,
        event="Maintenance detected",
        details="Cdn13 is under maintenance",
    )
    await asyncio.sleep(0.02)

    maintenance = [
        e for e in broker.get_events() if e.get("type") == "maintenance_detected"
    ]
    assert maintenance, "expected a maintenance_detected envelope"
    payload = maintenance[-1]
    assert payload["subdomain"] == "Cdn13"
    assert payload["affected_files_count"] == 7
    assert payload["status"] == "Maintenance"
