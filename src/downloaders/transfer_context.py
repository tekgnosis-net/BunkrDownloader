"""Per-job transfer state shared by every file a job downloads.

One :class:`TransferContext` is created per job (CLI run, batch URL, or web
job) and handed to every ``MediaDownloader`` of that job, including the
album retry pass:

- ``settings``: the job's resolved :class:`~src.config.TransferSettings`
  (built-in < env < per-job value), resolved once.
- ``governor``: the job's own :class:`ConnectionGovernor`, sized
  ``max(settings.max_connections, max_workers)`` so a worker is never starved
  of a slot; every segment worker and single stream holds one slot.
- ``cancel_event``: set by the web cancel endpoint or by Ctrl-C in the CLI;
  workers check it between chunks and before every backoff sleep, so a
  cancel stops the transfer within one chunk and leaves a resumable partial.
- ``started_at``: wall-clock start of the job; files modified since then
  belong to this run and are never treated as leftovers of an old build.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.config import MAX_WORKERS, TransferSettings, resolve_transfer_settings

from .connection_governor import ConnectionGovernor

if TYPE_CHECKING:
    from argparse import Namespace


@dataclass
class TransferContext:
    """Settings, connection cap and cancel flag for one job."""

    settings: TransferSettings
    governor: ConnectionGovernor
    cancel_event: threading.Event = field(default_factory=threading.Event)
    started_at: float = field(default_factory=time.time)

    @property
    def cancelled(self) -> bool:
        """Whether the job has been cancelled."""
        return self.cancel_event.is_set()


def make_transfer_context(
    args: Namespace | None, *, cancel_event: threading.Event | None = None,
) -> TransferContext:
    """Resolve the job's settings and build its governor and cancel flag."""
    settings = resolve_transfer_settings(args)
    max_workers = getattr(args, "max_workers", MAX_WORKERS) or MAX_WORKERS
    governor = ConnectionGovernor(max(settings.max_connections, int(max_workers)))
    return TransferContext(
        settings=settings,
        governor=governor,
        cancel_event=cancel_event if cancel_event is not None else threading.Event(),
    )
