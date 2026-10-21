"""Per-job cap on simultaneous streaming download connections.

Each job owns one :class:`ConnectionGovernor` through its
:class:`~src.downloaders.transfer_context.TransferContext`; every streaming
GET (a segment worker or a single stream) holds one slot for its lifetime.
A governor may have a ``parent`` (the optional process-wide ceiling): a slot
is then held in both, the job's own first and the parent's second, so the
scarcer process-wide slot is never held while waiting for a job slot.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


class Cancelled(Exception):
    """Raised from :meth:`ConnectionGovernor.slot` when a wait is abandoned.

    That happens when the caller's ``cancel_event`` (job cancelled) or
    ``stop_event`` (the caller's own fail-fast) is set while waiting.
    """


class ConnectionGovernor:
    """Counting gate: at most ``limit`` callers hold a slot at once.

    Implemented with a condition variable rather than a semaphore so the
    waits can also watch cancellation events and the limit can be raised
    without recreating the object every worker already references.
    """

    def __init__(self, limit: int, *, parent: ConnectionGovernor | None = None) -> None:
        self._limit = max(1, int(limit))
        self._in_flight = 0
        self._cond = threading.Condition()
        self._parent = parent

    @property
    def parent(self) -> ConnectionGovernor | None:
        """The governor whose slot is also held while one of ours is (or ``None``)."""
        return self._parent

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
    def slot(
        self,
        cancel_event: threading.Event | None = None,
        stop_event: threading.Event | None = None,
    ) -> Iterator[None]:
        """Hold one connection slot for the duration of the ``with`` block.

        While waiting for a free slot, raises :class:`Cancelled` as soon as
        either event is set (polled every 0.2 s). With a ``parent``, its
        slot is taken after ours and released before ours.
        """
        events = [event for event in (cancel_event, stop_event) if event is not None]
        with self._cond:
            while self._in_flight >= self._limit:
                if any(event.is_set() for event in events):
                    raise Cancelled()
                self._cond.wait(timeout=0.2)
            self._in_flight += 1
        try:
            if self._parent is None:
                yield
            else:
                with self._parent.slot(cancel_event=cancel_event, stop_event=stop_event):
                    yield
        finally:
            with self._cond:
                self._in_flight -= 1
                self._cond.notify()
