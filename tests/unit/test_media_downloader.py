"""Focused tests for :meth:`MediaDownloader._handle_request_exception` branches."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import RequestException

from src.config import DownloadInfo, HTTPStatus, NetworkContext, SessionInfo
from src.downloaders.media_downloader import MediaDownloader


def _make_downloader(
    fake_live_manager,
    tmp_path: Path,
    *,
    status_check: bool = True,
    strategy: str = "backoff",
) -> MediaDownloader:
    args = Namespace(
        skip_status_check=not status_check,
        status_cache_ttl=60,
        maintenance_strategy=strategy,
    )
    network = NetworkContext(
        status_page="https://status.example/",
        bunkr_api="https://api.example/api/vs",
        fallback_domain="example.cr",
        user_agent="test-agent/1.0",
        download_referer="https://referer.example/",
    )
    session_info = SessionInfo(
        args=args,
        bunkr_status={},
        download_path=str(tmp_path),
        network=network,
    )
    return MediaDownloader(
        session_info=session_info,
        download_info=DownloadInfo(
            download_link="https://cdn13.example/file.bin",
            filename="file.bin",
            task=0,
        ),
        live_manager=fake_live_manager,
        retries=3,
    )


def _fake_request_exception(status_code: int | None) -> RequestException:
    """Build a RequestException whose ``response`` matches ``status_code``."""

    err = RequestException("simulated")
    if status_code is None:
        err.response = None
    else:
        response = MagicMock()
        response.status_code = status_code
        err.response = response
    return err


@pytest.mark.parametrize(
    "status_code, current_status, strategy, expect_retry",
    [
        # Server-down + maintenance + backoff → retry with longer delay
        (HTTPStatus.SERVER_DOWN, "Maintenance", "backoff", True),
        # Server-down + maintenance + skip → stop retrying
        (HTTPStatus.SERVER_DOWN, "Maintenance", "skip", False),
        # Server-down + reported operational → retry (transient 521)
        (HTTPStatus.SERVER_DOWN, "Operational", "backoff", True),
        # Transient 429/503 → retry
        (HTTPStatus.TOO_MANY_REQUESTS, "Operational", "backoff", True),
        (HTTPStatus.SERVICE_UNAVAILABLE, "Operational", "backoff", True),
        # Bad gateway + no maintenance → one-shot failure (retries forced to 1)
        (HTTPStatus.BAD_GATEWAY, "Operational", "backoff", False),
        # Bad gateway + maintenance → retry
        (HTTPStatus.BAD_GATEWAY, "Maintenance", "backoff", True),
        # Generic 500-class (not mapped) → give up
        (HTTPStatus.INTERNAL_ERROR, "Operational", "backoff", False),
    ],
)
def test_handle_request_exception_branches(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    fake_live_manager,
    tmp_path: Path,
    status_code,
    current_status,
    strategy,
    expect_retry,
) -> None:
    """Exercise each documented branch of ``_handle_request_exception``."""

    downloader = _make_downloader(fake_live_manager, tmp_path, strategy=strategy)

    with (
        patch(
            "src.downloaders.media_downloader.refresh_server_status",
            return_value=(current_status, True),
        ),
        patch("src.downloaders.media_downloader.time.sleep"),
    ):
        result = downloader._handle_request_exception(  # pylint: disable=protected-access
            _fake_request_exception(status_code),
            attempt=0,
        )

    assert result is expect_retry


def test_maintenance_emits_structured_event(
    fake_live_manager,
    tmp_path: Path,
) -> None:
    """Maintenance path routes through ``update_maintenance`` rather than free-form logs."""

    downloader = _make_downloader(fake_live_manager, tmp_path, strategy="backoff")

    with (
        patch(
            "src.downloaders.media_downloader.refresh_server_status",
            return_value=("Maintenance", True),
        ),
        patch("src.downloaders.media_downloader.time.sleep"),
        patch("src.downloaders.media_downloader.log_maintenance_event"),
    ):
        downloader._handle_request_exception(  # pylint: disable=protected-access
            _fake_request_exception(HTTPStatus.SERVER_DOWN),
            attempt=0,
        )

    events = [evt for evt, _ in fake_live_manager.logs]
    assert "Maintenance detected" in events, fake_live_manager.logs
