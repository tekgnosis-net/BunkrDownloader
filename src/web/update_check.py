"""Periodic update-available check against the GitHub releases API.

The web shell shows an "update available: vX.Y.Z" notice when the running build
is older than the latest published GitHub release. To keep that check cheap and
private, the *backend* fetches the latest release at most once per TTL window
(a shared, lock-guarded module cache) and hands the frontend a ready-made
verdict, rather than letting every browser call GitHub directly — that would
burn the unauthenticated 60-req/hr/IP budget and leak each user's IP.

Every failure path collapses to "no update available": a GitHub outage,
malformed payload, or unparseable version can never surface an error the UI has
to handle.
"""

from __future__ import annotations

import re
import threading
import time

import requests

GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/tekgnosis-net/BunkrDownloader/releases/latest"
)
UPDATE_CHECK_TTL_SECONDS = 6 * 3600
_REQUEST_TIMEOUT_SECONDS = 5
_GITHUB_HEADERS = {"Accept": "application/vnd.github+json"}

_VERSION_RE = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)")

# Shared release cache. ``fetched_at`` keys validity: ``None`` => never fetched
# (force a fetch); a timestamp within the TTL => return ``tag`` as-is, even when
# it is ``None`` (a cached GitHub outage). Mutated in place under ``_cache_lock``
# — same pattern as ``bunkr_utils._status_cache`` — so no ``global`` is needed.
_cache_lock = threading.Lock()
_cache: dict[str, float | str | None] = {"fetched_at": None, "tag": None}


def parse_version(text: str) -> tuple[int, int, int] | None:
    """Parse ``X.Y.Z`` (optionally ``v``-prefixed) into an int triple.

    Returns ``None`` for anything that doesn't match, so non-semver strings such
    as ``"dev"`` or ``""`` are inert and never trigger an update notice.
    """
    if not text:
        return None
    match = _VERSION_RE.match(text.strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch))


def is_update_available(current: str, latest: str) -> bool:
    """Return ``True`` only when both versions parse and ``latest`` is newer."""
    current_parsed = parse_version(current)
    latest_parsed = parse_version(latest)
    if current_parsed is None or latest_parsed is None:
        return False
    return latest_parsed > current_parsed


def _fetch_latest_tag() -> str | None:
    """Best-effort single GitHub fetch; returns the tag or ``None`` on any failure."""
    try:
        response = requests.get(
            GITHUB_LATEST_RELEASE_URL,
            headers=_GITHUB_HEADERS,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        tag = response.json().get("tag_name")
    except ValueError:
        return None
    return tag if isinstance(tag, str) and tag else None


def get_latest_release(*, now: float | None = None) -> str | None:
    """Return the latest release ``tag_name``, cached for ``UPDATE_CHECK_TTL_SECONDS``.

    Fetches GitHub's ``releases/latest`` at most once per TTL window across all
    callers. Any transport error, non-200, or missing ``tag_name`` yields
    ``None`` and is cached for the same window so an outage can't be hammered.
    ``now`` is injectable for deterministic tests and defaults to
    :func:`time.monotonic`.
    """
    timestamp = time.monotonic() if now is None else now
    with _cache_lock:
        fetched_at = _cache["fetched_at"]
        if fetched_at is not None and timestamp - fetched_at < UPDATE_CHECK_TTL_SECONDS:
            return _cache["tag"]
        _cache["tag"] = _fetch_latest_tag()
        _cache["fetched_at"] = timestamp
        return _cache["tag"]


def get_update_status(current: str, *, now: float | None = None) -> dict:
    """Resolve the full update verdict for ``current`` against the latest release."""
    latest = get_latest_release(now=now)
    available = is_update_available(current, latest) if latest else False
    return {
        "current_version": current,
        "latest_version": latest,
        "update_available": available,
    }
