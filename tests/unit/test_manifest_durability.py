"""A manifest may only claim bytes that were synced to disk first (C1)."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

import os
import threading
from collections import defaultdict
from pathlib import Path

from requests.exceptions import ChunkedEncodingError

from src.downloaders import download_utils, segmented_download
from src.downloaders.download_utils import DownloadOutcome, save_file_with_progress
from src.downloaders.segmented_download import SegmentedDownloader, SegmentedOutcome
from src.downloaders.transfer_manifest import TransferManifest


def _record(monkeypatch) -> list[tuple[int, str]]:
    """Patch fdatasync, both save_manifest imports and shutil.move with recorders."""
    events: list[tuple[int, str]] = []
    real_sync = getattr(os, "fdatasync", os.fsync)

    def fake_sync(fd):
        events.append((threading.get_ident(), "sync"))
        real_sync(fd)
    monkeypatch.setattr(os, "fdatasync", fake_sync, raising=False)

    for module in (segmented_download, download_utils):
        def fake_save(manifest, path, _real=module.save_manifest):
            events.append((threading.get_ident(), "save"))
            _real(manifest, path)
        monkeypatch.setattr(module, "save_manifest", fake_save)

    real_move = download_utils.shutil.move

    def fake_move(src, dst):
        events.append((threading.get_ident(), "move"))
        return real_move(src, dst)
    monkeypatch.setattr(download_utils.shutil, "move", fake_move)
    return events


def _assert_synced_first(events: list[tuple[int, str]]) -> int:
    """Each save/move must follow a sync made by the same thread since its last save/move."""
    synced: dict[int, bool] = defaultdict(bool)
    checked = 0
    for thread_id, kind in events:
        if kind == "sync":
            synced[thread_id] = True
            continue
        assert synced[thread_id], f"{kind} without a preceding fdatasync: {events}"
        synced[thread_id] = False
        checked += 1
    return checked


class _PM:  # pylint: disable=too-few-public-methods
    def update_task(self, *_args, **_kwargs):
        return None


def test_segmented_every_manifest_save_follows_fdatasync(range_server, tmp_path, monkeypatch):
    events = _record(monkeypatch)
    manifest = TransferManifest.plan(len(range_server.data), 4, etag=range_server.etag)
    dl = SegmentedDownloader(url=range_server.url, headers={}, temp_path=tmp_path / "f.temp",
                             manifest=manifest, progress_manager=_PM(), task=0,
                             flush_bytes=256 * 1024)
    assert dl.run() is SegmentedOutcome.COMPLETE
    saves = sum(1 for _, kind in events if kind == "save")
    assert saves > 8                               # periodic + per-worker + final flushes
    assert _assert_synced_first(events) == saves


class _Response:  # pylint: disable=too-few-public-methods
    def __init__(self, chunks, headers):
        self._chunks = chunks
        self.headers = headers
        self.raw = None

    def iter_content(self, chunk_size=None):
        del chunk_size
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


def test_single_stream_periodic_and_final_saves_follow_fdatasync(
    tmp_path: Path, fake_live_manager, monkeypatch,
):
    events = _record(monkeypatch)
    monkeypatch.setattr(download_utils, "MANIFEST_FLUSH_BYTES", 16)
    manifest = TransferManifest.plan(64, 1, etag=None)
    response = _Response([b"a" * 16] * 4, {"Content-Length": "64"})
    final = tmp_path / "f.bin"
    outcome = save_file_with_progress(response, str(final), 0, fake_live_manager,
                                      manifest=manifest)
    assert outcome is DownloadOutcome.SUCCESS and final.read_bytes() == b"a" * 64
    kinds = [kind for _, kind in events]
    assert kinds.count("save") == 5                 # 4 periodic + post-loop
    assert kinds[-1] == "move"                      # rename comes last, after a sync
    assert _assert_synced_first(events) == 6


def test_single_stream_interrupted_save_follows_fdatasync(
    tmp_path: Path, fake_live_manager, monkeypatch,
):
    events = _record(monkeypatch)
    manifest = TransferManifest.plan(64, 1, etag=None)
    response = _Response([b"a" * 16, ChunkedEncodingError("cut")], {"Content-Length": "64"})
    outcome = save_file_with_progress(response, str(tmp_path / "f.bin"), 0, fake_live_manager,
                                      manifest=manifest)
    assert outcome is DownloadOutcome.RETRYABLE_FAILURE
    assert [kind for _, kind in events] == ["sync", "save"]
    assert manifest.segments[0].done == 16
