"""Abandoned .temp/.temp.parts older than the knob are removed at job start."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.config import AlbumInfo
from src.downloaders.album_downloader import AlbumDownloader
from src.downloaders.segmented_download import cleanup_stale_partials


def _old(path: Path, hours: float) -> None:
    ts = time.time() - hours * 3600
    os.utime(path, (ts, ts))


def test_cleanup_removes_only_old_pairs(tmp_path: Path):
    old = tmp_path / "a.temp"
    old.write_bytes(b"x")
    (tmp_path / "a.temp.parts").write_text("{}")
    _old(old, 200)
    _old(tmp_path / "a.temp.parts", 200)
    fresh = tmp_path / "b.temp"
    fresh.write_bytes(b"x")
    (tmp_path / "b.temp.parts").write_text("{}")
    legacy = tmp_path / "c.temp"  # no manifest: left alone
    legacy.write_bytes(b"x")
    _old(legacy, 200)
    removed = cleanup_stale_partials(tmp_path, 168)
    assert removed == [old]
    assert not old.exists() and not (tmp_path / "a.temp.parts").exists()
    assert fresh.exists() and (tmp_path / "b.temp.parts").exists() and legacy.exists()


def test_cleanup_disabled_with_zero(tmp_path: Path):
    old = tmp_path / "a.temp"
    old.write_bytes(b"x")
    (tmp_path / "a.temp.parts").write_text("{}")
    _old(old, 1000)
    _old(tmp_path / "a.temp.parts", 1000)
    # pylint: disable=use-implicit-booleaness-not-comparison
    assert cleanup_stale_partials(tmp_path, 0) == [] and old.exists()


def test_download_album_runs_cleanup_with_job_setting(fake_live_manager, session_info):
    class Args:  # pylint: disable=too-few-public-methods
        """Minimal args namespace."""

        partial_max_age_hours = 5
        max_workers = 1

    session_info.args = Args()
    album = AlbumDownloader(
        session_info=session_info,
        album_info=AlbumInfo(album_id="x", item_pages=[]),
        live_manager=fake_live_manager,
    )
    with patch(
        "src.downloaders.album_downloader.cleanup_stale_partials",
        return_value=[Path("/d/a.temp")],
    ) as cl, patch.object(album, "_process_failed_downloads", new=AsyncMock()):
        asyncio.run(album.download_album(max_workers=1))
    cl.assert_called_once()
    assert cl.call_args.args[1] == 5
    assert any("a.temp" in d for _, d in fake_live_manager.logs)
