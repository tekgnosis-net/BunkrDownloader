"""Governor caps concurrent slots, never lowers the cap below demand, honours cancel."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

import threading
import time

import pytest

from src.downloaders.connection_governor import Cancelled, ConnectionGovernor


def test_slot_caps_concurrency():
    gov = ConnectionGovernor(2)
    peak = 0
    lock = threading.Lock()

    def worker():
        nonlocal peak
        with gov.slot():
            with lock:
                peak = max(peak, gov.in_flight)
            time.sleep(0.05)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 2 and gov.in_flight == 0


def test_raise_limit_only_raises():
    gov = ConnectionGovernor(3)
    assert gov.raise_limit(2) == 3
    assert gov.raise_limit(5) == 5
    assert gov.limit == 5


def test_slot_wait_is_cancellable():
    gov = ConnectionGovernor(1)
    cancel = threading.Event()
    with gov.slot():
        cancel.set()
        with pytest.raises(Cancelled):
            with gov.slot(cancel_event=cancel):
                pass


def test_slot_wait_wakes_on_stop_event():
    gov = ConnectionGovernor(1)
    stop = threading.Event()
    raised = []

    def waiter():
        try:
            with gov.slot(stop_event=stop):
                pass
        except Cancelled:
            raised.append(True)
    with gov.slot():
        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.1)
        assert thread.is_alive()                  # still waiting for the held slot
        stop.set()
        thread.join(timeout=2)
    assert raised == [True] and gov.in_flight == 0


def test_parent_slot_caps_across_children():
    ceiling = ConnectionGovernor(2)
    jobs = [ConnectionGovernor(4, parent=ceiling) for _ in range(2)]
    peak = 0
    lock = threading.Lock()

    def worker(gov):
        nonlocal peak
        with gov.slot():
            with lock:
                peak = max(peak, ceiling.in_flight)
            time.sleep(0.05)

    threads = [threading.Thread(target=worker, args=(jobs[i % 2],)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 2 and ceiling.in_flight == 0
    assert all(gov.in_flight == 0 for gov in jobs)
    assert jobs[0].parent is ceiling


def test_parent_wait_honours_cancel():
    ceiling = ConnectionGovernor(1)
    child = ConnectionGovernor(4, parent=ceiling)
    cancel = threading.Event()
    with ceiling.slot():
        cancel.set()
        with pytest.raises(Cancelled):
            with child.slot(cancel_event=cancel):
                pass
    assert child.in_flight == 0 and ceiling.in_flight == 0
