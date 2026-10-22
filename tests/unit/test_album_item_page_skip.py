"""An album item page that cannot be loaded is skipped, never fatal to the job."""

# pylint: disable=missing-function-docstring,protected-access
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import requests
from bs4 import BeautifulSoup

from src import general_utils
from src.config import AlbumInfo
from src.downloaders.album_downloader import AlbumDownloader

PAGES = [f"https://bunkr.cr/f/item{i}" for i in range(3)]
BAD_PAGE = PAGES[1]


class _Args:
    skip_status_check = True
    status_cache_ttl = 60
    max_workers = 2


def _album(fake_live_manager, session_info) -> AlbumDownloader:
    session_info.args = _Args()
    return AlbumDownloader(
        session_info=session_info,
        album_info=AlbumInfo(album_id="x", item_pages=list(PAGES)),
        live_manager=fake_live_manager,
    )


async def _fetch(url: str, **_: object) -> BeautifulSoup | None:
    if url == BAD_PAGE:
        return None
    return BeautifulSoup("<html></html>", "html.parser")


def test_unloadable_item_page_is_skipped_and_album_continues(fake_live_manager, session_info):
    album = _album(fake_live_manager, session_info)
    downloaded = AsyncMock()
    with (
        patch("src.downloaders.album_downloader.fetch_page", new=_fetch),
        patch(
            "src.downloaders.album_downloader.get_download_info",
            new=AsyncMock(return_value=("https://cdn.example/x.mp4", "x.mp4")),
        ),
        patch.object(album, "_download_item", new=downloaded),
        patch("src.downloaders.album_downloader.cleanup_stale_partials", return_value=[]),
    ):
        asyncio.run(album.download_album(max_workers=2))

    # The two good items were downloaded, the bad one was not.
    assert downloaded.await_count == 2
    assert BAD_PAGE not in {call.args[3] for call in downloaded.await_args_list}
    # The skip was logged and its task row finished + hidden.
    skips = [d for e, d in fake_live_manager.logs if e == "Fetch failed"]
    assert skips == [f"Skipping {BAD_PAGE}: unable to load the album item page."]
    assert (1, {"completed": 100, "advance": 0, "visible": False}) in fake_live_manager.task_updates
    assert fake_live_manager.overall["total"] == 3


def _response(status: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = b"<html></html>"
    response.url = "https://bunkr.cr/f/gone"
    return response


def _run_fetch(monkeypatch, status: int) -> list[str]:
    logged: list[str] = []
    monkeypatch.setattr(general_utils, "write_on_session_log", logged.append)

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        headers: dict = {}

        def get(self, url, timeout):  # pylint: disable=unused-argument
            return _response(status)

    monkeypatch.setattr(general_utils.requests, "Session", _Session)
    assert asyncio.run(general_utils.fetch_page("https://bunkr.cr/f/gone")) is None
    return logged


def test_fetch_page_records_a_404_in_session_log_once(monkeypatch):
    assert _run_fetch(monkeypatch, 404) == ["https://bunkr.cr/f/gone"]


def test_fetch_page_records_a_502_in_session_log_once(monkeypatch):
    assert _run_fetch(monkeypatch, 502) == ["https://bunkr.cr/f/gone"]
