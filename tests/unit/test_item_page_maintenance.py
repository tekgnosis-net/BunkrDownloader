"""Item pages that say "Download unavailable ... maintenance" must be recognised."""

# pylint: disable=missing-function-docstring,protected-access,too-few-public-methods
from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from bs4 import BeautifulSoup

from src.config import AlbumInfo, SessionInfo
from src.crawlers import api_utils
from src.downloaders.album_downloader import AlbumDownloader

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _soup(name: str) -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"), "html.parser")


def test_detects_maintenance_page():
    reason = api_utils.detect_item_page_maintenance(_soup("item_page_maintenance.html"))
    assert reason is not None
    assert "maintenance" in reason.lower()


def test_healthy_page_is_not_maintenance_and_has_markers():
    soup = _soup("item_page_healthy.html")
    assert api_utils.detect_item_page_maintenance(soup) is None
    cdn, sign = api_utils.extract_media_sources(soup)
    assert cdn.startswith("https://") and cdn.endswith(".mp4")
    assert sign == "https://glb-apisign.cdn.cr/sign"


def test_signed_url_warning_names_maintenance(caplog):
    with caplog.at_level(logging.WARNING):
        assert api_utils.get_signed_download_url(_soup("item_page_maintenance.html")) is None
    assert any("maintenance" in r.getMessage().lower() for r in caplog.records)


def test_signed_url_warning_names_missing_markers(caplog):
    soup = BeautifulSoup("<html><body><p>hello</p></body></html>", "html.parser")
    with caplog.at_level(logging.WARNING):
        assert api_utils.get_signed_download_url(soup) is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("jsCDN" in m and "signUrl" in m for m in msgs)
    assert not any("maintenance" in m.lower() for m in msgs)


class _Args:  # minimal stand-in for argparse.Namespace
    def __init__(self, strategy: str) -> None:
        self.maintenance_strategy = strategy
        self.skip_status_check = True
        self.status_cache_ttl = 60


def _album(fake_live_manager, session_info: SessionInfo, strategy: str) -> AlbumDownloader:
    session_info.args = _Args(strategy)
    return AlbumDownloader(
        session_info=session_info,
        album_info=AlbumInfo(album_id="x", item_pages=["https://bunkr.cr/f/abc"]),
        live_manager=fake_live_manager,
    )


def test_album_item_maintenance_skip_strategy(fake_live_manager, session_info):
    album = _album(fake_live_manager, session_info, "skip")
    with (
        patch(
            "src.downloaders.album_downloader.fetch_page",
            new=AsyncMock(return_value=_soup("item_page_maintenance.html")),
        ),
        patch("src.downloaders.album_downloader.log_maintenance_event") as log_evt,
        patch("src.downloaders.album_downloader.asyncio.sleep", new=AsyncMock()) as slept,
    ):
        asyncio.run(
            album.execute_item_download("https://bunkr.cr/f/abc", 0, asyncio.Semaphore(1)),
        )

    events = [e for e, _ in fake_live_manager.logs]
    assert "Maintenance detected" in events
    assert "Maintenance skip" in events
    assert "Download link unresolved" not in events
    log_evt.assert_called_once()
    assert log_evt.call_args.args[2] == "https://bunkr.cr/f/abc"
    slept.assert_not_called()
    # task finished + hidden so overall progress can advance
    assert fake_live_manager.task_updates[-1][1]["completed"] == 100
    assert fake_live_manager.task_updates[-1][1]["visible"] is False


def test_album_item_maintenance_backoff_retries_then_skips(
    fake_live_manager, session_info, monkeypatch,
):
    monkeypatch.setattr(
        "src.downloaders.album_downloader.MAINTENANCE_BACKOFF_DELAYS_SECONDS", (1, 2),
    )
    album = _album(fake_live_manager, session_info, "backoff")
    fetch = AsyncMock(return_value=_soup("item_page_maintenance.html"))
    with (
        patch("src.downloaders.album_downloader.fetch_page", new=fetch),
        patch("src.downloaders.album_downloader.log_maintenance_event"),
        patch("src.downloaders.album_downloader.asyncio.sleep", new=AsyncMock()) as slept,
    ):
        asyncio.run(
            album.execute_item_download("https://bunkr.cr/f/abc", 0, asyncio.Semaphore(1)),
        )

    assert slept.await_count == 2
    assert [c.args[0] for c in slept.await_args_list] == [1, 2]
    assert fetch.await_count == 3  # initial + one re-fetch per delay
    events = [e for e, _ in fake_live_manager.logs]
    assert events.count("Waiting for maintenance") == 2
    assert "Maintenance skip" in events


def test_album_item_maintenance_backoff_recovers(
    fake_live_manager, session_info, monkeypatch,
):
    monkeypatch.setattr(
        "src.downloaders.album_downloader.MAINTENANCE_BACKOFF_DELAYS_SECONDS", (1,),
    )
    album = _album(fake_live_manager, session_info, "backoff")
    fetch = AsyncMock(
        side_effect=[_soup("item_page_maintenance.html"), _soup("item_page_healthy.html")],
    )
    with (
        patch("src.downloaders.album_downloader.fetch_page", new=fetch),
        patch("src.downloaders.album_downloader.log_maintenance_event"),
        patch("src.downloaders.album_downloader.asyncio.sleep", new=AsyncMock()),
        patch(
            "src.downloaders.album_downloader.get_download_info",
            new=AsyncMock(
                side_effect=[(None, "f.mp4"), ("https://cdn.example/f.mp4?token=t", "f.mp4")],
            ),
        ),
        patch("src.downloaders.album_downloader.MediaDownloader") as media_cls,
    ):
        media_cls.return_value.download.return_value = None
        asyncio.run(
            album.execute_item_download("https://bunkr.cr/f/abc", 0, asyncio.Semaphore(1)),
        )

    media_cls.assert_called_once()
    download_info = media_cls.call_args.kwargs["download_info"]
    assert download_info.download_link.startswith("https://cdn.example/")
    events = [e for e, _ in fake_live_manager.logs]
    assert "Maintenance skip" not in events


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, (120, 300, 600)),
        ("5,10", (5, 10)),
        ("0,7200", (1, 3600)),
        ("junk", (120, 300, 600)),
        ("", (120, 300, 600)),
    ],
)
def test_maintenance_backoff_delays_knob(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("MAINTENANCE_BACKOFF_DELAYS_SECONDS", raising=False)
    else:
        monkeypatch.setenv("MAINTENANCE_BACKOFF_DELAYS_SECONDS", raw)
    from src import config  # pylint: disable=import-outside-toplevel

    try:
        assert importlib.reload(config).MAINTENANCE_BACKOFF_DELAYS_SECONDS == expected
    finally:
        monkeypatch.delenv("MAINTENANCE_BACKOFF_DELAYS_SECONDS", raising=False)
        importlib.reload(config)
