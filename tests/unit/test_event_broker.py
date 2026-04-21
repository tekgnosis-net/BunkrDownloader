"""Regression tests for :class:`JobEventBroker` envelope + subscribe semantics."""

from __future__ import annotations

import asyncio
import threading

import pytest

from src.web.app import JobEventBroker


@pytest.mark.asyncio
async def test_broadcast_stamps_monotonic_event_id_and_ts() -> None:
    """Every envelope leaves the broker with a strictly monotonic ``event_id``."""

    broker = JobEventBroker()
    broker.bind(asyncio.get_running_loop())

    for i in range(5):
        broker.publish({"type": "log", "event": f"e{i}", "details": ""})

    events = broker.get_events()
    assert [e["event_id"] for e in events] == [1, 2, 3, 4, 5]
    assert all("ts" in e for e in events)


@pytest.mark.asyncio
async def test_subscribe_does_not_drop_events_during_replay() -> None:
    """Snapshot-then-register must be atomic — neither drop nor duplicate."""

    broker = JobEventBroker()
    broker.bind(asyncio.get_running_loop())

    # Pre-fill 50 events before subscribe begins
    for i in range(50):
        broker.publish({"type": "log", "event": f"e{i}", "details": ""})

    received: list[dict] = []

    async def consume() -> None:
        async for ev in broker.subscribe():
            received.append(ev)
            if len(received) >= 100:
                break

    task = asyncio.create_task(consume())
    # Yield so the subscribe generator registers before we publish more.
    await asyncio.sleep(0)
    for i in range(50):
        broker.publish({"type": "log", "event": f"live-{i}", "details": ""})
    await task

    assert len(received) == 100
    assert [e["event_id"] for e in received] == list(range(1, 101))


@pytest.mark.asyncio
async def test_event_id_monotonic_across_threads() -> None:
    """Cross-thread publish (via ``call_soon_threadsafe``) preserves ordering."""

    broker = JobEventBroker()
    loop = asyncio.get_running_loop()
    broker.bind(loop)

    def worker(n: int) -> None:
        for i in range(n):
            broker.publish({"type": "log", "event": str(i), "details": ""})

    threads = [threading.Thread(target=worker, args=(100,)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Drain any deferred call_soon_threadsafe closures.
    for _ in range(10):
        await asyncio.sleep(0.01)

    events = broker.get_events()
    assert len(events) == 500
    assert [e["event_id"] for e in events] == list(range(1, 501))


@pytest.mark.asyncio
async def test_get_events_filters_by_event_id() -> None:
    """``since`` semantics are by ``event_id``, not list index."""

    broker = JobEventBroker()
    broker.bind(asyncio.get_running_loop())

    for i in range(10):
        broker.publish({"type": "log", "event": f"e{i}", "details": ""})

    tail = broker.get_events(since=5)
    assert [e["event_id"] for e in tail] == [6, 7, 8, 9, 10]


def test_broker_requires_bind_before_publish() -> None:
    """``publish`` before ``bind`` raises a clear RuntimeError rather than crashing."""

    broker = JobEventBroker()
    with pytest.raises(RuntimeError):
        broker.publish({"type": "log", "event": "e", "details": ""})
