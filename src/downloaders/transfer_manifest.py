"""On-disk manifest that makes a partially downloaded file resumable.

``<final>.temp`` holds the bytes; ``<final>.temp.parts`` (this module) records
the remote size/ETag and, per segment, how many bytes have been written
contiguously from the segment start. Workers only ever append within their
own range, so ``done`` is always a prefix length — there are no holes.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_VERSION = 1
_SAVE_LOCK = threading.Lock()


@dataclass
class Segment:
    """Inclusive byte range ``[start, end]`` plus bytes completed from ``start``."""

    start: int
    end: int
    done: int = 0

    @property
    def length(self) -> int:
        """Total bytes in this segment."""
        return self.end - self.start + 1

    @property
    def remaining(self) -> int:
        """Bytes still to fetch."""
        return self.length - self.done

    @property
    def complete(self) -> bool:
        """Whether every byte of the segment is on disk."""
        return self.done >= self.length

    @property
    def next_offset(self) -> int:
        """Absolute file offset of the next byte to write."""
        return self.start + self.done


@dataclass
class TransferManifest:
    """Resumable-transfer state for one file."""

    size: int
    etag: str | None
    segments: list[Segment] = field(default_factory=list)
    url_origin: str | None = None

    @classmethod
    def plan(
        cls,
        size: int,
        segment_count: int,
        *,
        etag: str | None,
        url_origin: str | None = None,
    ) -> TransferManifest:
        """Split ``[0, size)`` into ``segment_count`` contiguous ranges.

        The first ``size % n`` segments are one byte longer so the ranges
        tile the file exactly for any size.
        """
        count = max(1, min(segment_count, size)) if size > 0 else 1
        base, extra = divmod(size, count)
        segments: list[Segment] = []
        start = 0
        for index in range(count):
            length = base + (1 if index < extra else 0)
            segments.append(Segment(start=start, end=start + length - 1))
            start += length
        return cls(size=size, etag=etag, segments=segments, url_origin=url_origin)

    @property
    def bytes_done(self) -> int:
        """Bytes on disk across all segments."""
        return sum(segment.done for segment in self.segments)

    @property
    def complete(self) -> bool:
        """Whether all segments are fully written."""
        return bool(self.segments) and all(segment.complete for segment in self.segments)

    def to_dict(self) -> dict:
        """Serialisable form (see spec §On-disk layout)."""
        return {
            "version": MANIFEST_VERSION,
            "url_origin": self.url_origin,
            "size": self.size,
            "etag": self.etag,
            "segment_size": self.segments[0].length if self.segments else 0,
            "segments": [
                {"start": s.start, "end": s.end, "done": s.done} for s in self.segments
            ],
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    @classmethod
    def from_dict(cls, data: dict) -> TransferManifest:
        """Inverse of :meth:`to_dict`; raises ``ValueError`` on bad shape.

        Validates the invariants the resume logic relies on: non-negative
        size, a string-or-null ETag, contiguous segments starting at 0 that
        tile ``[0, size)`` exactly, and ``0 <= done <= length`` per segment.
        """
        if data.get("version") != MANIFEST_VERSION:
            raise ValueError("unsupported manifest version")
        size = int(data["size"])
        if size < 0:
            raise ValueError("negative manifest size")
        etag = data.get("etag")
        if etag is not None and not isinstance(etag, str):
            raise ValueError("manifest etag must be a string or null")
        segments = [
            Segment(start=int(s["start"]), end=int(s["end"]), done=int(s.get("done", 0)))
            for s in data["segments"]
        ]
        if not segments:
            raise ValueError("manifest has no segments")
        expected_start = 0
        for segment in segments:
            if segment.end < segment.start - 1 or segment.start != expected_start:
                raise ValueError("manifest segments are not contiguous")
            if not 0 <= segment.done <= segment.length:
                raise ValueError("manifest segment progress out of range")
            expected_start = segment.end + 1
        if segments[-1].end != size - 1:
            raise ValueError("manifest segments do not cover the file")
        return cls(
            size=size,
            etag=etag,
            segments=segments,
            url_origin=data.get("url_origin"),
        )


def manifest_path(temp_path: Path) -> Path:
    """Return the sidecar path for a ``.temp`` data file."""
    return temp_path.with_name(temp_path.name + ".parts")


def save_manifest(manifest: TransferManifest, path: Path) -> None:
    """Write the manifest atomically (temp file + ``os.replace``).

    Safe to call from multiple threads; atomic against process death (no
    fsync, so not against power loss). A failed write removes the temp file
    and re-raises.
    """
    tmp = path.with_name(path.name + ".tmp")
    with _SAVE_LOCK:
        try:
            tmp.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise


def load_manifest(path: Path) -> TransferManifest | None:
    """Load a manifest, returning ``None`` when absent, malformed or outdated."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TransferManifest.from_dict(data)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _etag_value(etag: str | None) -> str | None:
    if etag is None:
        return None
    value = etag.strip()
    if value.startswith("W/"):
        value = value[2:]
    return value.strip('"') or None


def manifest_matches_remote(
    manifest: TransferManifest, *, size: int | None, etag: str | None,
) -> bool:
    """Whether local partial bytes may be trusted against the remote object.

    Size must match exactly. ETag must match when both sides have one
    (weak validators compare by value); either side lacking an ETag falls
    back to the size check alone because the CDN publishes no checksum.
    """
    if size is None or size != manifest.size:
        return False
    local, remote = _etag_value(manifest.etag), _etag_value(etag)
    if local is None or remote is None:
        return True
    return local == remote


def discard_partial(temp_path: Path) -> None:
    """Delete the data file and its manifest; missing files are not an error."""
    for path in (temp_path, manifest_path(temp_path)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
