"""Parallel byte-range transfer into one pre-sized file, resumable via a manifest.

See docs/superpowers/specs/2026-10-21-segmented-resumable-downloads-design.md.
"""

from __future__ import annotations

import errno
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import requests
from requests.exceptions import ChunkedEncodingError, RequestException

from src.config import HTTPStatus, TransferSettings
from src.managers.progress_manager import ProgressManager

from .connection_governor import GOVERNOR, Cancelled, ConnectionGovernor
from .download_utils import MANIFEST_FLUSH_BYTES, get_chunk_size
from .remote_probe import RemoteInfo
from .transfer_manifest import (
    Segment,
    TransferManifest,
    manifest_path,
    save_manifest,
    sync_data,
)


class TransferMode(Enum):
    """How a file will be fetched."""

    SINGLE_NO_RESUME = "single_no_resume"   # unknown size or no Range support
    SINGLE = "single"                       # one stream, manifest-backed resume
    SEGMENTED = "segmented"                 # N range workers


class SegmentedOutcome(Enum):
    """Result of one :meth:`SegmentedDownloader.run`."""

    COMPLETE = "complete"
    RETRYABLE = "retryable"
    NEEDS_REFRESH = "needs_refresh"          # 401/403: signed URL expired
    RANGE_UNSUPPORTED = "range_unsupported"  # server answered 200 to a Range GET
    MANIFEST_INVALID = "manifest_invalid"    # 416 / Content-Range mismatch
    TERMINAL = "terminal"                    # disk error
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TransferPlan:
    """Decision produced by :func:`plan_transfer`."""

    mode: TransferMode
    manifest: TransferManifest | None
    remote: RemoteInfo


def plan_transfer(
    remote: RemoteInfo,
    settings: TransferSettings,
    *,
    existing: TransferManifest | None,
    url_origin: str | None,
) -> TransferPlan:
    """Choose single vs segmented and build (or adopt) the manifest.

    ``existing`` must already have been validated against ``remote`` by the
    caller (see ``manifest_matches_remote``); it is adopted as-is so its
    segment layout and progress survive.
    """
    if remote.size is None or not remote.accepts_ranges:
        return TransferPlan(TransferMode.SINGLE_NO_RESUME, None, remote)

    if existing is not None:
        mode = TransferMode.SEGMENTED if len(existing.segments) > 1 else TransferMode.SINGLE
        return TransferPlan(mode, existing, remote)

    if settings.segments <= 1 or remote.size < settings.segment_min_bytes:
        manifest = TransferManifest.plan(remote.size, 1, etag=remote.etag, url_origin=url_origin)
        return TransferPlan(TransferMode.SINGLE, manifest, remote)

    by_min_size = max(1, math.floor(remote.size / settings.segment_min_bytes))
    count = min(settings.segments, by_min_size)
    manifest = TransferManifest.plan(remote.size, count, etag=remote.etag, url_origin=url_origin)
    mode = TransferMode.SEGMENTED if count > 1 else TransferMode.SINGLE
    return TransferPlan(mode, manifest, remote)


class _LinkExpired(Exception):
    """401/403 from the CDN: the signed URL is no longer valid."""


class _RangeUnsupported(Exception):
    """Server answered 200 to a Range request."""


class _Stopped(Exception):
    """Worker halted by our own fail-fast; a side effect, never an outcome."""


class _ManifestInvalid(Exception):
    """416 or Content-Range disagreement: local offsets are wrong."""


class SegmentedDownloader:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """Fetch every incomplete segment of ``manifest`` in parallel into ``temp_path``."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        url: str,
        headers: dict[str, str],
        temp_path: Path,
        manifest: TransferManifest,
        progress_manager: ProgressManager,
        task: int,
        governor: ConnectionGovernor = GOVERNOR,
        cancel_event: threading.Event | None = None,
        timeout: float = 30.0,
        flush_bytes: int = MANIFEST_FLUSH_BYTES,
    ) -> None:
        self.url = url
        self.headers = headers
        self.temp_path = temp_path
        self.manifest = manifest
        self.progress_manager = progress_manager
        self.task = task
        self.governor = governor
        self.cancel_event = cancel_event or threading.Event()
        self.timeout = timeout
        self.flush_bytes = flush_bytes
        self._lock = threading.Lock()
        self._total = manifest.bytes_done
        self._fd: int | None = None
        self._stop = threading.Event()
        # Flush ordering: a snapshot taken earlier never overwrites a newer save.
        self._save_order = threading.Lock()
        self._generation = 0
        self._saved_generation = 0

    # ---- public -----------------------------------------------------------

    def run(self) -> SegmentedOutcome:
        """Run all incomplete segments; always leaves a consistent manifest on disk."""
        try:
            file_ok = self._prepare_file()
        except OSError as os_err:
            logging.warning("Cannot prepare %s: %s", self.temp_path, os_err)
            self._close_fd()
            return SegmentedOutcome.TERMINAL
        if not file_ok:
            self._close_fd()
            return SegmentedOutcome.MANIFEST_INVALID

        pending = [s for s in self.manifest.segments if not s.complete]
        if not pending:
            flushed = self._try_flush()
            self._close_fd()
            return SegmentedOutcome.COMPLETE if flushed else SegmentedOutcome.TERMINAL

        outcome = SegmentedOutcome.COMPLETE
        try:
            with ThreadPoolExecutor(max_workers=len(pending)) as pool:
                futures = [pool.submit(self._fetch_segment, seg) for seg in pending]
                for future in futures:
                    try:
                        future.result()
                    except (Cancelled, _Stopped, _LinkExpired, _RangeUnsupported,
                            _ManifestInvalid, OSError, RequestException,
                            ChunkedEncodingError) as exc:
                        result = _classify(exc)
                        outcome = _worst(outcome, result)
                        if result is not SegmentedOutcome.RETRYABLE:
                            self._stop.set()   # private fail-fast; caller's event untouched
        finally:
            flushed = self._try_flush()
            self._close_fd()
        if not flushed:
            return SegmentedOutcome.TERMINAL

        if outcome is SegmentedOutcome.COMPLETE and not self.manifest.complete:
            return SegmentedOutcome.RETRYABLE
        if outcome is SegmentedOutcome.RANGE_UNSUPPORTED:
            for seg in self.manifest.segments:
                seg.done = 0
            if not self._try_flush():
                return SegmentedOutcome.TERMINAL
        return outcome

    # ---- internals ----------------------------------------------------------

    def _close_fd(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _prepare_file(self) -> bool:
        """Open and pre-size the temp file; False if recorded progress has no backing data."""
        existed = self.temp_path.exists()
        self._fd = os.open(self.temp_path, os.O_RDWR | os.O_CREAT, 0o644)
        intact = existed and os.fstat(self._fd).st_size == self.manifest.size
        if not intact:
            if self.manifest.bytes_done > 0:
                return False
            os.ftruncate(self._fd, self.manifest.size)
        return True

    def _try_flush(self) -> bool:
        try:
            self._flush()
        except OSError as os_err:
            logging.warning("Cannot save manifest for %s: %s", self.temp_path, os_err)
            return False
        return True

    def _flush(self) -> None:
        """Snapshot progress, make the data durable, then save the snapshot.

        ``done`` values are captured under ``_lock``; every byte they count
        was ``pwrite``-n before the capture, so the ``fdatasync`` that follows
        covers them. No lock is held across the sync (it can take seconds on
        a NAS). An ``OSError`` from the sync or the save propagates: callers
        treat it as a flush failure.
        """
        with self._lock:
            self._generation += 1
            generation = self._generation
            snapshot = self.manifest.snapshot()
        if self._fd is not None:
            sync_data(self._fd)
        with self._save_order:
            if generation < self._saved_generation:
                return
            save_manifest(snapshot, manifest_path(self.temp_path))
            self._saved_generation = generation

    def _advance(self, segment: Segment, delta: int) -> None:
        """Count ``delta`` freshly written bytes for ``segment`` and report progress."""
        with self._lock:
            segment.done += delta
            self._total += delta
            size = self.manifest.size
            pct = min(100.0, self._total / size * 100) if size else 0.0
            self.progress_manager.update_task(self.task, completed=pct)

    def _check_stop(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()
        if self._stop.is_set():
            raise _Stopped()

    def _write_chunk(self, segment: Segment, chunk: bytes) -> int:
        """Write ``chunk`` at the segment cursor, looping over short writes."""
        assert self._fd is not None
        view = memoryview(chunk[: segment.remaining])
        total = 0
        while total < len(view):
            written = os.pwrite(self._fd, view[total:], segment.next_offset)
            if written <= 0:
                raise OSError(errno.EIO, "pwrite wrote 0 bytes")
            total += written
            self._advance(segment, written)
        return total

    def _fetch_segment(self, segment: Segment) -> None:
        self._check_stop()
        headers = dict(self.headers)
        headers["Accept-Encoding"] = "identity"
        headers["Range"] = f"bytes={segment.next_offset}-{segment.end}"
        with self.governor.slot(cancel_event=self.cancel_event):
            self._check_stop()
            with requests.get(self.url, headers=headers, stream=True, timeout=self.timeout) as resp:
                self._check_response(resp, segment)
                chunk_size = get_chunk_size(segment.length)
                since_flush = 0
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    self._check_stop()
                    if not chunk:
                        continue
                    since_flush += self._write_chunk(segment, chunk)
                    if since_flush >= self.flush_bytes:
                        self._flush()
                        since_flush = 0
                    if segment.complete:
                        break
        self._flush()

    def _check_response(self, resp: requests.Response, segment: Segment) -> None:
        if resp.status_code in (HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED):
            raise _LinkExpired()
        if resp.status_code == HTTPStatus.RANGE_NOT_SATISFIABLE:
            raise _ManifestInvalid()
        if resp.status_code == HTTPStatus.OK:
            raise _RangeUnsupported()
        resp.raise_for_status()
        if resp.status_code != HTTPStatus.PARTIAL_CONTENT:
            raise _ManifestInvalid()
        content_range = resp.headers.get("Content-Range", "")
        expected = f"bytes {segment.next_offset}-{segment.end}/{self.manifest.size}"
        if content_range.replace(" ", "") != expected.replace(" ", ""):
            raise _ManifestInvalid()


_SEVERITY = {
    SegmentedOutcome.COMPLETE: 0,
    SegmentedOutcome.RETRYABLE: 1,
    # CANCELLED outranks RETRYABLE: a user cancel must not be retried; real
    # protocol/disk failures outrank both.
    SegmentedOutcome.CANCELLED: 2,
    SegmentedOutcome.NEEDS_REFRESH: 3,
    SegmentedOutcome.RANGE_UNSUPPORTED: 4,
    SegmentedOutcome.MANIFEST_INVALID: 5,
    SegmentedOutcome.TERMINAL: 6,
}


def _worst(current: SegmentedOutcome, new: SegmentedOutcome) -> SegmentedOutcome:
    """Keep the more severe of two outcomes."""
    return new if _SEVERITY[new] > _SEVERITY[current] else current


def _classify(exc: Exception) -> SegmentedOutcome:
    """Map a worker exception to the outcome it represents."""
    if isinstance(exc, _Stopped):
        return SegmentedOutcome.COMPLETE   # side effect of another failure: no vote
    if isinstance(exc, Cancelled):
        return SegmentedOutcome.CANCELLED
    if isinstance(exc, _LinkExpired):
        return SegmentedOutcome.NEEDS_REFRESH
    if isinstance(exc, _RangeUnsupported):
        return SegmentedOutcome.RANGE_UNSUPPORTED
    if isinstance(exc, _ManifestInvalid):
        return SegmentedOutcome.MANIFEST_INVALID
    if isinstance(exc, OSError) and not isinstance(exc, RequestException):
        return SegmentedOutcome.TERMINAL
    return SegmentedOutcome.RETRYABLE


def cleanup_stale_partials(
    directory: Path, max_age_hours: int, *, now: float | None = None,
) -> list[Path]:
    """Delete ``*.temp`` + ``*.temp.parts`` pairs older than ``max_age_hours``.

    Only pairs are touched: a lone ``.temp`` from an older build has no
    manifest and is left for the existing "discard on next attempt" path.
    ``0`` disables the sweep.
    """
    if max_age_hours <= 0 or not directory.is_dir():
        return []
    cutoff = (now if now is not None else time.time()) - max_age_hours * 3600
    removed: list[Path] = []
    for parts in sorted(directory.glob("*.temp.parts")):
        temp = parts.with_name(parts.name[: -len(".parts")])
        try:
            newest = max(parts.stat().st_mtime, temp.stat().st_mtime if temp.exists() else 0)
        except OSError:
            continue
        if newest >= cutoff:
            continue
        if not _unlink_quietly(temp) or not _unlink_quietly(parts):
            continue
        removed.append(temp)
    return removed


def _unlink_quietly(path: Path) -> bool:
    """Remove ``path``; True when it is gone afterwards, False on any other OSError."""
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError as err:
        logging.debug("Could not remove stale partial %s: %s", path, err)
        return False
    return True
