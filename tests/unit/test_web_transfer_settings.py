"""Transfer knobs over the web API: validation, precedence, defaults endpoint."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

from fastapi.testclient import TestClient

from src.web.app import DownloadRequest, _build_namespace, app


def test_settings_defaults_exposes_download_section():
    with TestClient(app) as client:
        body = client.get("/api/settings/defaults").json()
    assert body["download"] == {
        "max_workers": 3, "segments": 4, "segment_min_size_mb": 32,
        "max_connections": 12, "partial_max_age_hours": 168,
        "link_refresh_max": 2, "manifest_reset_max": 1,
    }


def test_request_fields_validated():
    with TestClient(app) as client:
        resp = client.post(
            "/api/downloads", json={"urls": ["https://bunkr.cr/a/x"], "segments": 99}
        )
    assert resp.status_code == 422


def test_namespace_preserves_absent_and_present_fields():
    req = DownloadRequest(urls=["https://bunkr.cr/a/x"])
    ns = _build_namespace("https://bunkr.cr/a/x", req)
    assert ns.segments is None and ns.max_connections is None
    req = DownloadRequest(urls=["https://bunkr.cr/a/x"], segments=2, segment_min_size_mb=64,
                          max_connections=5, partial_max_age_hours=0)
    ns = _build_namespace("https://bunkr.cr/a/x", req)
    assert (ns.segments, ns.segment_min_size_mb, ns.max_connections,
            ns.partial_max_age_hours) == (2, 64, 5, 0)
