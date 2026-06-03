"""Unit tests for the periodic update-available checker.

Covers the three pure helpers (``parse_version``, ``is_update_available``,
``get_update_status``), the TTL-cached GitHub fetch (``get_latest_release``)
including its graceful-degradation paths, and the ``/api/update-check``
endpoint shape. The module-level release cache is reset around every test so
ordering can't leak state.
"""

# Thin response doubles and protected-attribute resets are intentional in
# tests; bs4/TestClient imports stay lazy to keep collection cheap.
# pylint: disable=missing-function-docstring,protected-access,too-few-public-methods,import-outside-toplevel
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from src.web import update_check


@pytest.fixture(autouse=True)
def _clear_release_cache():
    """Each test starts and ends with an empty release cache."""
    update_check._cache.update(fetched_at=None, tag=None)
    yield
    update_check._cache.update(fetched_at=None, tag=None)


class _Resp:
    """Minimal stand-in for a ``requests.Response``."""

    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


# --------------------------------------------------------------------------- #
# parse_version
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected",
    [
        ("0.11.5", (0, 11, 5)),
        ("v0.11.5", (0, 11, 5)),
        ("V1.2.3", (1, 2, 3)),
        ("1.20.300", (1, 20, 300)),
    ],
)
def test_parse_version_accepts_semver(text, expected):
    assert update_check.parse_version(text) == expected


@pytest.mark.parametrize("text", ["dev", "1.2", "", "v", "latest", "x.y.z"])
def test_parse_version_rejects_non_semver(text):
    assert update_check.parse_version(text) is None


# --------------------------------------------------------------------------- #
# is_update_available
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("latest", ["0.11.6", "0.12.0", "1.0.0"])
def test_is_update_available_true_when_latest_newer(latest):
    assert update_check.is_update_available("0.11.5", latest) is True


def test_is_update_available_false_when_equal():
    assert update_check.is_update_available("0.11.5", "0.11.5") is False
    assert update_check.is_update_available("0.11.5", "v0.11.5") is False


def test_is_update_available_false_when_ahead():
    assert update_check.is_update_available("0.12.0", "0.11.5") is False


@pytest.mark.parametrize(
    "current,latest",
    [("dev", "0.11.6"), ("0.11.5", "garbage"), ("", "0.11.6")],
)
def test_is_update_available_false_when_unparseable(current, latest):
    assert update_check.is_update_available(current, latest) is False


# --------------------------------------------------------------------------- #
# get_latest_release (cache + degradation)
# --------------------------------------------------------------------------- #
def test_get_latest_release_returns_tag_name():
    resp = _Resp(payload={"tag_name": "v0.11.6"})
    with patch.object(update_check.requests, "get", return_value=resp) as mock_get:
        assert update_check.get_latest_release(now=0.0) == "v0.11.6"
        mock_get.assert_called_once()


def test_get_latest_release_caches_within_ttl():
    resp = _Resp(payload={"tag_name": "v0.11.6"})
    with patch.object(update_check.requests, "get", return_value=resp) as mock_get:
        first = update_check.get_latest_release(now=100.0)
        almost_expired = 100.0 + update_check.UPDATE_CHECK_TTL_SECONDS - 1
        second = update_check.get_latest_release(now=almost_expired)
    assert first == second == "v0.11.6"
    mock_get.assert_called_once()


def test_get_latest_release_refetches_after_ttl():
    responses = [_Resp(payload={"tag_name": "v0.11.6"}), _Resp(payload={"tag_name": "v0.11.7"})]
    with patch.object(update_check.requests, "get", side_effect=responses) as mock_get:
        first = update_check.get_latest_release(now=100.0)
        expired = 100.0 + update_check.UPDATE_CHECK_TTL_SECONDS + 1
        second = update_check.get_latest_release(now=expired)
    assert first == "v0.11.6"
    assert second == "v0.11.7"
    assert mock_get.call_count == 2


def test_get_latest_release_none_on_request_exception():
    with patch.object(
        update_check.requests, "get", side_effect=requests.RequestException("boom"),
    ) as mock_get:
        assert update_check.get_latest_release(now=0.0) is None
        mock_get.assert_called_once()


def test_get_latest_release_caches_failure_within_ttl():
    """A GitHub outage must be cached so it isn't hammered every request."""
    with patch.object(
        update_check.requests, "get", side_effect=requests.RequestException("boom"),
    ) as mock_get:
        assert update_check.get_latest_release(now=0.0) is None
        assert update_check.get_latest_release(now=1.0) is None
    mock_get.assert_called_once()


def test_get_latest_release_none_on_non_200():
    resp = _Resp(status_code=404, payload={"message": "Not Found"})
    with patch.object(update_check.requests, "get", return_value=resp):
        assert update_check.get_latest_release(now=0.0) is None


def test_get_latest_release_none_on_missing_tag():
    resp = _Resp(status_code=200, payload={"name": "no tag here"})
    with patch.object(update_check.requests, "get", return_value=resp):
        assert update_check.get_latest_release(now=0.0) is None


# --------------------------------------------------------------------------- #
# get_update_status
# --------------------------------------------------------------------------- #
def test_get_update_status_reports_available():
    resp = _Resp(payload={"tag_name": "v9.9.9"})
    with patch.object(update_check.requests, "get", return_value=resp):
        status = update_check.get_update_status("0.11.5", now=0.0)
    assert status == {
        "current_version": "0.11.5",
        "latest_version": "v9.9.9",
        "update_available": True,
    }


def test_get_update_status_handles_github_down():
    with patch.object(
        update_check.requests, "get", side_effect=requests.RequestException("boom"),
    ):
        status = update_check.get_update_status("0.11.5", now=0.0)
    assert status == {
        "current_version": "0.11.5",
        "latest_version": None,
        "update_available": False,
    }


# --------------------------------------------------------------------------- #
# /api/update-check endpoint
# --------------------------------------------------------------------------- #
def test_update_check_endpoint_shape():
    from fastapi.testclient import TestClient

    from src.web.app import APP_VERSION, app

    resp = _Resp(payload={"tag_name": "v9.9.9"})
    with patch.object(update_check.requests, "get", return_value=resp):
        with TestClient(app) as client:
            response = client.get("/api/update-check")

    assert response.status_code == 200
    body = response.json()
    assert body["current_version"] == APP_VERSION
    assert body["latest_version"] == "v9.9.9"
    assert body["update_available"] is True
