# tests/unit/test_remote_probe.py
"""HEAD probe: size/etag/range support extraction and failure shape."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

from unittest.mock import MagicMock

import requests

from src.downloaders import remote_probe


def _resp(status=200, **headers):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


def test_probe_parses_size_etag_and_ranges(monkeypatch):
    seen = {}

    def fake_head(url, **kwargs):
        seen.update(kwargs, url=url)
        return _resp(
            **{"Content-Length": "1428977356", "ETag": '"6714a1c2"', "Accept-Ranges": "bytes"}
        )

    monkeypatch.setattr(remote_probe.requests, "head", fake_head)
    info = remote_probe.probe_remote(
        "https://cdn.example/f.mp4", {"User-Agent": "ua"}, timeout=3
    )
    assert info.size == 1428977356 and info.etag == '"6714a1c2"' and info.accepts_ranges
    assert seen["headers"] == {"User-Agent": "ua"}
    assert seen["timeout"] == 3 and seen["allow_redirects"] is True


def test_probe_without_ranges_or_length(monkeypatch):
    monkeypatch.setattr(
        remote_probe.requests, "head", lambda *a, **k: _resp(**{"Accept-Ranges": "none"})
    )
    info = remote_probe.probe_remote("u", {})
    assert info.size is None and info.etag is None and not info.accepts_ranges


def test_probe_failure_is_soft(monkeypatch):
    def boom(*_a, **_k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(remote_probe.requests, "head", boom)
    assert remote_probe.probe_remote("u", {}) == remote_probe.RemoteInfo(None, None, False)
    monkeypatch.setattr(remote_probe.requests, "head", lambda *a, **k: _resp(status=403))
    assert remote_probe.probe_remote("u", {}) == remote_probe.RemoteInfo(None, None, False)
