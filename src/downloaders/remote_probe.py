"""One HEAD request per file to learn size, ETag and Range support."""

from __future__ import annotations

from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class RemoteInfo:
    """What the server told us about the object before any GET."""

    size: int | None
    etag: str | None
    accepts_ranges: bool


_UNKNOWN = RemoteInfo(size=None, etag=None, accepts_ranges=False)


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def probe_remote(url: str, headers: dict[str, str], *, timeout: float = 30.0) -> RemoteInfo:
    """HEAD ``url`` with the same headers the GET will use.

    Returns :data:`RemoteInfo` with ``size=None`` / ``accepts_ranges=False``
    on any network error or non-2xx status so callers degrade to a plain
    single-stream download instead of failing the file.
    """
    try:
        response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
    except requests.RequestException:
        return _UNKNOWN
    accept = str(response.headers.get("Accept-Ranges", "")).lower()
    return RemoteInfo(
        size=_positive_int(response.headers.get("Content-Length")),
        etag=response.headers.get("ETag") or None,
        accepts_ranges="bytes" in accept,
    )
