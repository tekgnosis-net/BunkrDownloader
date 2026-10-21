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
                          max_connections=5)
    ns = _build_namespace("https://bunkr.cr/a/x", req)
    assert (ns.segments, ns.segment_min_size_mb, ns.max_connections) == (2, 64, 5)


def test_namespace_passes_all_six_transfer_fields_and_preserves_none():
    req = DownloadRequest(urls=["https://bunkr.cr/a/x"])
    ns = _build_namespace("https://bunkr.cr/a/x", req)
    assert ns.partial_max_age_hours is None
    assert ns.link_refresh_max is None and ns.manifest_reset_max is None
    req = DownloadRequest(urls=["https://bunkr.cr/a/x"], partial_max_age_hours=24,
                          link_refresh_max=4, manifest_reset_max=0)
    ns = _build_namespace("https://bunkr.cr/a/x", req)
    assert (ns.partial_max_age_hours, ns.link_refresh_max, ns.manifest_reset_max) == (24, 4, 0)


def test_link_refresh_and_reset_bounds_rejected():
    with TestClient(app) as client:
        for field, value in (("link_refresh_max", 11), ("manifest_reset_max", 6),
                             ("partial_max_age_hours", 8761)):
            resp = client.post(
                "/api/downloads", json={"urls": ["https://bunkr.cr/a/x"], field: value}
            )
            assert resp.status_code == 422
