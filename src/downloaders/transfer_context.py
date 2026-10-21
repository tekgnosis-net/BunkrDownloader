"""Per-job transfer state shared by every file a job downloads.

One :class:`TransferContext` is created per job (CLI run, batch URL, or web
job) and handed to every ``MediaDownloader`` of that job, including the
album retry pass:

- ``settings``: the job's resolved :class:`~src.config.TransferSettings`
  (built-in < env < per-job value), resolved once.
- ``governor``: the job's own :class:`ConnectionGovernor`, sized
  ``max(settings.max_connections, max_workers)`` so a worker is never starved
  of a slot; every segment worker and single stream holds one slot. When
  ``MAX_TOTAL_CONNECTIONS`` is set, the job governor's parent is the one
  process-wide :func:`process_ceiling`, so a slot counts against both.
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

from src import config
from src.config import MAX_WORKERS, TransferSettings, resolve_transfer_settings

from .connection_governor import ConnectionGovernor

if TYPE_CHECKING:
    from argparse import Namespace

_CEILING_LOCK = threading.Lock()
_CEILING: ConnectionGovernor | None = None


def process_ceiling() -> ConnectionGovernor | None:
    """The process-wide governor for ``MAX_TOTAL_CONNECTIONS``; ``None`` when unset (0).

    Built once and shared by every job; rebuilt only if the configured limit
    changes (tests reload the config).
    """
    global _CEILING  # pylint: disable=global-statement
    limit = int(config.MAX_TOTAL_CONNECTIONS)
    if limit <= 0:
        return None
    with _CEILING_LOCK:
        if _CEILING is None or _CEILING.limit != limit:
            _CEILING = ConnectionGovernor(limit)
        return _CEILING


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
    ceiling: ConnectionGovernor | None | object = ...,
) -> TransferContext:
    """Resolve the job's settings and build its governor and cancel flag.

    ``ceiling`` defaults to :func:`process_ceiling`; pass ``None`` for none.
    """
    settings = resolve_transfer_settings(args)
    max_workers = getattr(args, "max_workers", MAX_WORKERS) or MAX_WORKERS
    parent = process_ceiling() if ceiling is ... else ceiling
    assert parent is None or isinstance(parent, ConnectionGovernor)
    governor = ConnectionGovernor(max(settings.max_connections, int(max_workers)), parent=parent)
    return TransferContext(
        settings=settings,
        governor=governor,
        cancel_event=cancel_event if cancel_event is not None else threading.Event(),
    )
