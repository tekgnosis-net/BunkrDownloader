"""Process-wide cap on simultaneous streaming download connections."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from src.config import MAX_CONCURRENT_CONNECTIONS


class Cancelled(Exception):
    """Raised from :meth:`ConnectionGovernor.slot` when the job is cancelled while waiting."""


class ConnectionGovernor:
    """Counting gate: at most ``limit`` callers hold a slot at once.

    Implemented with a condition variable rather than a semaphore so the
    limit can be raised at job start (``max(limit, max_workers)``) without
    recreating the object every worker already references.
    """

    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._in_flight = 0
        self._cond = threading.Condition()

    @property
    def limit(self) -> int:
        """Current cap."""
        return self._limit

    @property
    def in_flight(self) -> int:
        """Slots currently held."""
        return self._in_flight

    def raise_limit(self, minimum: int) -> int:
        """Ensure the cap is at least ``minimum``; return the effective cap."""
        with self._cond:
            if minimum > self._limit:
                self._limit = int(minimum)
                self._cond.notify_all()
            return self._limit

    @contextmanager
    def slot(self, cancel_event: threading.Event | None = None) -> Iterator[None]:
        """Hold one connection slot for the duration of the ``with`` block."""
        with self._cond:
            while self._in_flight >= self._limit:
                if cancel_event is not None and cancel_event.is_set():
                    raise Cancelled()
                self._cond.wait(timeout=0.2)
            self._in_flight += 1
        try:
            yield
        finally:
            with self._cond:
                self._in_flight -= 1
                self._cond.notify()


GOVERNOR = ConnectionGovernor(MAX_CONCURRENT_CONNECTIONS)
