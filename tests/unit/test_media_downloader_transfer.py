# tests/unit/test_media_downloader_transfer.py
"""MediaDownloader: probe → manifest validation → plan → run, and link refresh."""

# pylint: disable=missing-function-docstring,protected-access,line-too-long
# pylint: disable=too-many-arguments
from __future__ import annotations

import hashlib
import os
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import patch

import requests

from src.config import (
    DownloadInfo, NetworkContext, SessionInfo, resolve_transfer_settings,
)
from src.downloaders.download_utils import DownloadOutcome
from src.downloaders import media_downloader
from src.downloaders.media_downloader import MediaDownloader
from src.downloaders.remote_probe import RemoteInfo
from src.downloaders.segmented_download import SegmentedDownloader, SegmentedOutcome
from src.downloaders.transfer_manifest import TransferManifest, manifest_path, save_manifest


def _dl(fake_live_manager, tmp_path, url, *, segments=4, min_mb=1, item_page=None, extra=None):
    args = Namespace(skip_status_check=True, status_cache_ttl=60, maintenance_strategy="skip",
                     segments=segments, segment_min_size_mb=min_mb, max_connections=12,
                     partial_max_age_hours=0, max_workers=1)
    for key, value in (extra or {}).items():
        setattr(args, key, value)
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


# --- review fixes -----------------------------------------------------------

def _seed_single(range_server, tmp_path, *, done, temp_bytes):
    """Write a one-segment manifest with ``done`` bytes claimed; temp holds ``temp_bytes``."""
    final = tmp_path / "file.bin"
    temp = final.with_suffix(".temp")
    manifest = TransferManifest.plan(len(range_server.data), 1, etag=range_server.etag)
    manifest.segments[0].done = done
    if temp_bytes is not None:
        temp.write_bytes(range_server.data[:temp_bytes])
    save_manifest(manifest, manifest_path(temp))
    return final, temp


def test_single_resume_with_missing_temp_restarts_from_zero(range_server, tmp_path, fake_live_manager):
    final, _ = _seed_single(range_server, tmp_path, done=1000, temp_bytes=None)
    dl = _dl(fake_live_manager, tmp_path, range_server.url, min_mb=100)
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert _sha(final.read_bytes()) == _sha(range_server.data)


def test_single_resume_with_short_temp_restarts_from_zero(range_server, tmp_path, fake_live_manager):
    final, _ = _seed_single(range_server, tmp_path, done=1000, temp_bytes=500)
    dl = _dl(fake_live_manager, tmp_path, range_server.url, min_mb=100)
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert _sha(final.read_bytes()) == _sha(range_server.data)


def test_single_resume_with_wrong_content_range_restarts(range_server, tmp_path, fake_live_manager):
    final, _ = _seed_single(range_server, tmp_path, done=1000, temp_bytes=1000)
    dl = _dl(fake_live_manager, tmp_path, range_server.url, min_mb=100)
    real_get = requests.get
    closed = []
    fake = SimpleNamespace(status_code=206, headers={"Content-Range": "bytes 0-9/10"},
                           close=lambda: closed.append(True), raise_for_status=lambda: None)
    ranged = []

    def fake_get(url, **kwargs):
        if "Range" in (kwargs.get("headers") or {}):
            ranged.append(1)
            return fake
        return real_get(url, **kwargs)  # pylint: disable=missing-timeout
    with patch("src.downloaders.media_downloader.requests.get", side_effect=fake_get):
        assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert ranged == [1] and closed
    assert _sha(final.read_bytes()) == _sha(range_server.data)


def test_probe_failure_keeps_partial(range_server, tmp_path, fake_live_manager):
    final, temp = _seed_single(range_server, tmp_path, done=1000, temp_bytes=1000)
    dl = _dl(fake_live_manager, tmp_path, range_server.url, min_mb=100)
    with patch("src.downloaders.media_downloader.probe_remote",
               return_value=RemoteInfo(None, None, False)):
        assert dl.attempt_download(str(final)) is DownloadOutcome.RETRYABLE_FAILURE
    assert temp.exists() and manifest_path(temp).exists()
    assert any("keeping partial" in d for _, d in fake_live_manager.logs)


def test_refresh_cap_is_bounded(range_server, tmp_path, fake_live_manager):
    range_server.forbid_from_request = 1
    dl = _dl(fake_live_manager, tmp_path, range_server.url, item_page="https://bunkr.cr/f/abc",
             extra={"link_refresh_max": 2})
    with patch.object(dl, "_refresh_link", side_effect=lambda: range_server.url + "?t=x") as refresh, \
            patch.object(MediaDownloader, "_pause", return_value=True):
        assert dl.attempt_download(str(tmp_path / "file.bin")) is DownloadOutcome.RETRYABLE_FAILURE
    assert refresh.call_count == 2


def test_manifest_reset_max_zero_is_terminal(range_server, tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, range_server.url, extra={"manifest_reset_max": 0})
    with patch.object(SegmentedDownloader, "run", autospec=True,
                      return_value=SegmentedOutcome.MANIFEST_INVALID):
        assert dl.attempt_download(str(tmp_path / "file.bin")) is DownloadOutcome.TERMINAL_FAILURE


def test_manifest_invalid_gets_one_restart_even_with_single_retry(range_server, tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    dl.retries = 1
    real_run = SegmentedDownloader.run
    calls = []

    def run(self):
        calls.append(1)
        if len(calls) == 1:
            return SegmentedOutcome.MANIFEST_INVALID
        return real_run(self)
    final = tmp_path / "file.bin"
    with patch.object(SegmentedDownloader, "run", autospec=True, side_effect=run):
        assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert len(calls) == 2
    assert _sha(final.read_bytes()) == _sha(range_server.data)


def test_refresh_reprobes_and_replans_when_remote_changed(range_server, tmp_path, fake_live_manager):
    range_server.forbid_from_request = 3
    dl = _dl(fake_live_manager, tmp_path, range_server.url, item_page="https://bunkr.cr/f/abc")
    real_probe = media_downloader.probe_remote
    probes = []

    def probe(url, headers):
        probes.append(url)
        if len(probes) == 1:
            return real_probe(url, headers)
        return RemoteInfo(len(range_server.data), '"new-etag"', True)

    def fake_refresh():
        range_server.forbid_from_request = None
        return range_server.url + "?token=fresh"
    final = tmp_path / "file.bin"
    with patch.object(dl, "_refresh_link", side_effect=fake_refresh), \
            patch("src.downloaders.media_downloader.probe_remote", side_effect=probe), \
            patch("src.downloaders.media_downloader.discard_partial",
                  wraps=media_downloader.discard_partial) as discard:
        assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert len(probes) == 2 and probes[1].endswith("?token=fresh")
    discard.assert_called()
    assert any("after link refresh" in d for _, d in fake_live_manager.logs)
    assert _sha(final.read_bytes()) == _sha(range_server.data)


def test_refresh_link_returns_none_for_page_without_markers(range_server, tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, range_server.url, item_page="https://bunkr.cr/f/abc")
    page = SimpleNamespace(text="<html></html>", raise_for_status=lambda: None)
    with patch("src.downloaders.media_downloader.requests.get", return_value=page):
        assert dl._refresh_link() is None


def test_single_refresh_hands_off_to_segmented_when_replan_is_segmented(
    range_server, tmp_path, fake_live_manager,
):
    range_server.forbid_from_request = 1
    dl = _dl(fake_live_manager, tmp_path, range_server.url, min_mb=100,
             item_page="https://bunkr.cr/f/abc")
    real_probe = media_downloader.probe_remote
    probes = []

    def probe(url, headers):
        probes.append(url)
        if len(probes) == 1:
            return real_probe(url, headers)
        return RemoteInfo(len(range_server.data), '"new-etag"', True)

    def fake_refresh():
        range_server.forbid_from_request = None
        return range_server.url + "?token=fresh"
    # The re-plan must be segmented: lower the threshold after the first (single) plan.
    real_replan = dl._replan_after_refresh

    def replan(*args, **kwargs):
        dl._settings = resolve_transfer_settings(Namespace(
            segments=4, segment_min_size_mb=1, max_connections=12, partial_max_age_hours=0))
        return real_replan(*args, **kwargs)
    final = tmp_path / "file.bin"
    with patch.object(dl, "_refresh_link", side_effect=fake_refresh), \
            patch.object(dl, "_replan_after_refresh", side_effect=replan), \
            patch("src.downloaders.media_downloader.probe_remote", side_effect=probe), \
            patch.object(dl, "_run_segmented", wraps=dl._run_segmented) as seg:
        assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    seg.assert_called_once()
    assert _sha(final.read_bytes()) == _sha(range_server.data)


def test_zero_progress_manifest_with_unknown_probe_is_dropped(range_server, tmp_path, fake_live_manager):
    final, temp = _seed_single(range_server, tmp_path, done=0, temp_bytes=0)
    dl = _dl(fake_live_manager, tmp_path, range_server.url, min_mb=100)
    with patch("src.downloaders.media_downloader.probe_remote",
               return_value=RemoteInfo(None, None, False)):
        assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert _sha(final.read_bytes()) == _sha(range_server.data)
    assert not manifest_path(temp).exists()
