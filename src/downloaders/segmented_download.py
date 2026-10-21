"""Parallel byte-range transfer into one pre-sized file, resumable via a manifest.

See docs/superpowers/specs/2026-10-21-segmented-resumable-downloads-design.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from src.config import TransferSettings

from .remote_probe import RemoteInfo
from .transfer_manifest import TransferManifest

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
