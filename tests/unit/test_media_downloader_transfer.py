# tests/unit/test_media_downloader_transfer.py
"""MediaDownloader: probe → manifest validation → plan → run, and link refresh."""

# pylint: disable=missing-function-docstring,protected-access,line-too-long
# pylint: disable=multiple-statements,too-many-arguments
from __future__ import annotations

import hashlib
import os
from argparse import Namespace
from unittest.mock import patch

from src.config import DownloadInfo, NetworkContext, SessionInfo
from src.downloaders.download_utils import DownloadOutcome
from src.downloaders.media_downloader import MediaDownloader
from src.downloaders.transfer_manifest import TransferManifest, manifest_path, save_manifest


def _dl(fake_live_manager, tmp_path, url, *, segments=4, min_mb=1, item_page=None):
    args = Namespace(skip_status_check=True, status_cache_ttl=60, maintenance_strategy="skip",
                     segments=segments, segment_min_size_mb=min_mb, max_connections=12,
                     partial_max_age_hours=0, max_workers=1)
    network = NetworkContext(status_page="https://s.example/", bunkr_api="https://a.example/",
                             fallback_domain="example.cr", user_agent="t/1", download_referer="https://r.example/")
    si = SessionInfo(args=args, bunkr_status={}, download_path=str(tmp_path), network=network)
    return MediaDownloader(session_info=si,
                           download_info=DownloadInfo(download_link=url, filename="file.bin", task=0, item_page=item_page),
                           live_manager=fake_live_manager, retries=3)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_attempt_download_segmented_end_to_end(range_server, tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    final = tmp_path / "file.bin"
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert _sha(final.read_bytes()) == _sha(range_server.data)
    assert not manifest_path(final.with_suffix(".temp")).exists()
    assert range_server.get_count == 4


def test_attempt_download_single_stream_below_threshold(range_server, tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, range_server.url, min_mb=100)   # 5 MB file < 100 MB
    final = tmp_path / "file.bin"
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert range_server.get_count == 1 and _sha(final.read_bytes()) == _sha(range_server.data)


def test_attempt_download_resumes_existing_manifest_and_logs(range_server, tmp_path, fake_live_manager):
    final = tmp_path / "file.bin"
    temp = final.with_suffix(".temp")
    manifest = TransferManifest.plan(len(range_server.data), 4, etag=range_server.etag)
    s0 = manifest.segments[0]
    with temp.open("wb") as fh:
        fh.truncate(len(range_server.data))
        fh.seek(0)
        fh.write(range_server.data[: s0.length])
    s0.done = s0.length
    save_manifest(manifest, manifest_path(temp))
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert range_server.get_count == 3
    assert any("Resuming" in d for _, d in fake_live_manager.logs)


def test_attempt_download_discards_mismatched_manifest(range_server, tmp_path, fake_live_manager):
    final = tmp_path / "file.bin"
    temp = final.with_suffix(".temp")
    stale = TransferManifest.plan(len(range_server.data) + 1, 4, etag='"old"')
    stale.segments[0].done = 1000
    temp.write_bytes(b"\0" * 1000)
    save_manifest(stale, manifest_path(temp))
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert _sha(final.read_bytes()) == _sha(range_server.data)
    assert any("stale partial" in d for _, d in fake_live_manager.logs)


def test_attempt_download_refreshes_expired_link(range_server, tmp_path, fake_live_manager):
    range_server.forbid_from_request = 3
    dl = _dl(fake_live_manager, tmp_path, range_server.url, item_page="https://bunkr.cr/f/abc")

    def fake_refresh():
        range_server.forbid_from_request = None
        return range_server.url + "?token=fresh"
    with patch.object(dl, "_refresh_link", side_effect=fake_refresh) as refresh:
        assert dl.attempt_download(str(tmp_path / "file.bin")) is DownloadOutcome.SUCCESS
    refresh.assert_called_once()
    assert dl.download_info.download_link.endswith("?token=fresh")


def test_attempt_download_range_unsupported_falls_back(range_server, tmp_path, fake_live_manager):
    range_server.ignore_range = True
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    final = tmp_path / "file.bin"
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert _sha(final.read_bytes()) == _sha(range_server.data)


def test_refresh_link_without_item_page_is_none(range_server, tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    assert dl._refresh_link() is None


def test_segmented_downgrades_to_resumable_single_without_pwrite(
    range_server, tmp_path, fake_live_manager, monkeypatch,
):
    monkeypatch.delattr(os, "pwrite", raising=False)
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    final = tmp_path / "file.bin"
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert range_server.get_count == 1
    assert _sha(final.read_bytes()) == _sha(range_server.data)
