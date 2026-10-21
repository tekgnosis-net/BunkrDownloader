"""Parallel byte-range transfer into one pre-sized file, resumable via a manifest.

See docs/superpowers/specs/2026-10-21-segmented-resumable-downloads-design.md.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import requests
from requests.exceptions import ChunkedEncodingError, RequestException

from src.config import HTTPStatus, TransferSettings
from src.managers.progress_manager import ProgressManager

from .connection_governor import GOVERNOR, Cancelled, ConnectionGovernor
from .download_utils import get_chunk_size
from .remote_probe import RemoteInfo
from .transfer_manifest import Segment, TransferManifest, manifest_path, save_manifest

MANIFEST_FLUSH_BYTES = 8 * 1024 * 1024


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

    # ---- public -----------------------------------------------------------

    def run(self) -> SegmentedOutcome:
        """Run all incomplete segments; always leaves a consistent manifest on disk."""
        try:
            self._prepare_file()
        except OSError as os_err:
            logging.warning("Cannot prepare %s: %s", self.temp_path, os_err)
            return SegmentedOutcome.TERMINAL

        pending = [s for s in self.manifest.segments if not s.complete]
        if not pending:
            self._flush()
            return SegmentedOutcome.COMPLETE

        outcome = SegmentedOutcome.COMPLETE
        try:
            with ThreadPoolExecutor(max_workers=len(pending)) as pool:
                futures = [pool.submit(self._fetch_segment, seg) for seg in pending]
                for future in futures:
                    try:
                        future.result()
                    except (Cancelled, _LinkExpired, _RangeUnsupported, _ManifestInvalid,
                            OSError, RequestException, ChunkedEncodingError) as exc:
                        result = _classify(exc)
                        outcome = _worst(outcome, result)
                        if result is not SegmentedOutcome.RETRYABLE:
                            self.cancel_event.set()
        finally:
            self._flush()
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

        if outcome is SegmentedOutcome.COMPLETE and not self.manifest.complete:
            return SegmentedOutcome.RETRYABLE
        if outcome is SegmentedOutcome.RANGE_UNSUPPORTED:
            for seg in self.manifest.segments:
                seg.done = 0
            self._flush()
        return outcome

    # ---- internals ----------------------------------------------------------

    def _prepare_file(self) -> None:
        flags = os.O_RDWR | os.O_CREAT
        self._fd = os.open(self.temp_path, flags, 0o644)
        if os.fstat(self._fd).st_size != self.manifest.size:
            os.ftruncate(self._fd, self.manifest.size)

    def _flush(self) -> None:
        with self._lock:
            save_manifest(self.manifest, manifest_path(self.temp_path))

    def _report(self, delta: int) -> None:
        with self._lock:
            self._total += delta
            size = self.manifest.size
            pct = min(100.0, self._total / size * 100) if size else 0.0
        self.progress_manager.update_task(self.task, completed=pct)

    def _fetch_segment(self, segment: Segment) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()
        headers = dict(self.headers)
        headers["Range"] = f"bytes={segment.next_offset}-{segment.end}"
        with self.governor.slot(cancel_event=self.cancel_event):
            with requests.get(self.url, headers=headers, stream=True, timeout=self.timeout) as resp:
                self._check_response(resp, segment)
                chunk_size = get_chunk_size(segment.length)
                since_flush = 0
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if self.cancel_event.is_set():
                        raise Cancelled()
                    if not chunk:
                        continue
                    chunk = chunk[: segment.remaining]
                    assert self._fd is not None
                    written = os.pwrite(self._fd, chunk, segment.next_offset)
                    segment.done += written
                    since_flush += written
                    self._report(written)
                    if since_flush >= self.flush_bytes:
                        self._flush()
                        since_flush = 0
                    if segment.complete:
                        break
        self._flush()

    def _check_response(self, resp: requests.Response, segment: Segment) -> None:
        if resp.status_code in (HTTPStatus.FORBIDDEN, 401):
            raise _LinkExpired()
        if resp.status_code == 416:
            raise _ManifestInvalid()
        if resp.status_code == HTTPStatus.OK:
            raise _RangeUnsupported()
        resp.raise_for_status()
        if resp.status_code != 206:
            raise _ManifestInvalid()
        content_range = resp.headers.get("Content-Range", "")
        expected = f"bytes {segment.next_offset}-{segment.end}/{self.manifest.size}"
        if content_range.replace(" ", "") != expected.replace(" ", ""):
            raise _ManifestInvalid()


_SEVERITY = {
    SegmentedOutcome.COMPLETE: 0,
    SegmentedOutcome.RETRYABLE: 1,
    SegmentedOutcome.CANCELLED: 2,       # below real failures: siblings cancelled by our
    SegmentedOutcome.NEEDS_REFRESH: 3,   # own fail-fast must not mask the root cause
    SegmentedOutcome.RANGE_UNSUPPORTED: 4,
    SegmentedOutcome.MANIFEST_INVALID: 5,
    SegmentedOutcome.TERMINAL: 6,
}


def _worst(current: SegmentedOutcome, new: SegmentedOutcome) -> SegmentedOutcome:
    """Keep the more severe of two outcomes."""
    return new if _SEVERITY[new] > _SEVERITY[current] else current


def _classify(exc: Exception) -> SegmentedOutcome:
    """Map a worker exception to the outcome it represents."""
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
