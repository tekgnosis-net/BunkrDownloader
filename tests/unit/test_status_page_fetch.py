"""Status-page fetch failures must be quiet and the timeout must be a knob."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

import importlib
import logging

import pytest
import requests

from src import bunkr_utils


def _boom(*_args, **_kwargs):
    raise requests.ReadTimeout("HTTPSConnectionPool(host='status.example'): Read timed out.")


def test_fetch_page_failure_logs_single_warning_without_traceback(monkeypatch, caplog):
    monkeypatch.setattr(bunkr_utils.requests, "get", _boom)
    with caplog.at_level(logging.INFO, logger=""):
        assert bunkr_utils.fetch_page("https://status.example/") is None

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "status.example" in warnings[0].getMessage()
    assert "ReadTimeout" in warnings[0].getMessage()
    # No traceback rendered at INFO and above.
    assert "Traceback" not in caplog.text
    assert not any(r.exc_info for r in warnings)


def test_fetch_page_failure_keeps_traceback_at_debug(monkeypatch, caplog):
    monkeypatch.setattr(bunkr_utils.requests, "get", _boom)
    with caplog.at_level(logging.DEBUG, logger=""):
        bunkr_utils.fetch_page("https://status.example/")
    debug = [r for r in caplog.records if r.levelno == logging.DEBUG and r.exc_info]
    assert debug, "traceback should still be available at DEBUG"


def test_fetch_page_uses_status_page_timeout_knob(monkeypatch):
    seen = {}

    def fake_get(_url, **kwargs):
        seen.update(kwargs)
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(bunkr_utils.requests, "get", fake_get)
    monkeypatch.setattr(bunkr_utils, "STATUS_PAGE_TIMEOUT_SECONDS", 7)
    bunkr_utils.fetch_page("https://status.example/")
    assert seen["timeout"] == 7


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 10), ("3", 3), ("0", 1), ("-5", 1), ("999", 60), ("abc", 10)],
)
def test_status_page_timeout_env_default_and_clamp(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("STATUS_PAGE_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("STATUS_PAGE_TIMEOUT_SECONDS", raw)
    from src import config  # pylint: disable=import-outside-toplevel

    reloaded = importlib.reload(config)
    try:
        assert reloaded.STATUS_PAGE_TIMEOUT_SECONDS == expected
    finally:
        monkeypatch.delenv("STATUS_PAGE_TIMEOUT_SECONDS", raising=False)
        importlib.reload(config)
