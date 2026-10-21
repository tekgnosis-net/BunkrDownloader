"""downloader.py: the job's TransferContext reaches every file and Ctrl-C cancels it."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

import asyncio
from argparse import Namespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

import downloader
from src.config import AlbumInfo, SessionInfo
from src.downloaders.album_downloader import AlbumDownloader
from src.downloaders.transfer_context import make_transfer_context

SINGLE_URL = "https://bunkr.cr/f/abc123"


def _args(tmp_path) -> Namespace:
    return Namespace(disable_disk_check=True, custom_path=str(tmp_path), log_level="info",
                     max_workers=1)


@pytest.mark.parametrize("interrupt", [asyncio.CancelledError, KeyboardInterrupt])
async def test_interrupt_sets_the_transfer_cancel_event(tmp_path, fake_live_manager, interrupt):
    ctx = make_transfer_context(None)
    soup = BeautifulSoup("<html></html>", "html.parser")
    with patch.object(downloader, "fetch_page", AsyncMock(return_value=soup)), \
            patch.object(downloader, "get_album_name", return_value="x"), \
            patch.object(downloader, "create_download_directory", return_value=str(tmp_path)), \
            patch.object(downloader, "handle_download_process",
                         AsyncMock(side_effect=interrupt)) as handle:
        with pytest.raises(interrupt):
            await downloader.validate_and_download(
                {}, SINGLE_URL, fake_live_manager, args=_args(tmp_path), transfer_context=ctx,
            )
    assert ctx.cancel_event.is_set()
    assert handle.call_args.args[-1] is ctx


async def test_single_file_gets_item_page_and_job_context(tmp_path, fake_live_manager):
    ctx = make_transfer_context(None)
    session = SessionInfo(args=_args(tmp_path), bunkr_status={}, download_path=str(tmp_path),
                          network=None)
    soup = BeautifulSoup("<html></html>", "html.parser")
    media = MagicMock()
    with patch.object(downloader, "get_download_info",
                      AsyncMock(return_value=("https://cdn.example/x.bin", "x.bin"))), \
            patch.object(downloader, "MediaDownloader", return_value=media) as media_cls:
        await downloader.handle_download_process(session, SINGLE_URL, soup, fake_live_manager,
                                                 ctx)
    kwargs = media_cls.call_args.kwargs
    assert kwargs["download_info"].item_page == SINGLE_URL
    assert kwargs["transfer_context"] is ctx
    media.download.assert_called_once()


async def test_album_items_and_retry_pass_share_the_job_context(fake_live_manager, session_info):
    ctx = make_transfer_context(None)
    album = AlbumDownloader(session_info=session_info, album_info=AlbumInfo("x", []),
                            live_manager=fake_live_manager, transfer_context=ctx)
    media = MagicMock()
    media.download.return_value = None
    with patch("src.downloaders.album_downloader.MediaDownloader", return_value=media) as cls:
        await album._download_item(  # pylint: disable=protected-access
            "https://cdn.example/x.bin", "x.bin", 0, "https://bunkr.cr/f/x")
        await album._retry_failed_download(  # pylint: disable=protected-access
            0, "x.bin", "https://cdn.example/x.bin", None)
    assert cls.call_count == 2
    assert all(call.kwargs["transfer_context"] is ctx for call in cls.call_args_list)


def test_album_builds_its_own_context_when_none_is_given(fake_live_manager, session_info):
    album = AlbumDownloader(session_info=session_info, album_info=AlbumInfo("x", []),
                            live_manager=fake_live_manager)
    assert album.transfer_context is not None and not album.transfer_context.cancelled
