"""plan_transfer decisions and the SegmentedDownloader against a local range server."""

# pylint: disable=missing-function-docstring,too-many-arguments
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

from src.config import TransferSettings
from src.downloaders.connection_governor import ConnectionGovernor
from src.downloaders.remote_probe import RemoteInfo
from src.downloaders.segmented_download import (
    SegmentedDownloader,
    SegmentedOutcome,
    TransferMode,
    plan_transfer,
)
from src.downloaders.transfer_manifest import TransferManifest, load_manifest, manifest_path

SETTINGS = TransferSettings(segments=4, segment_min_bytes=32 * 1024 * 1024,
                            max_connections=12, partial_max_age_hours=168,
                            link_refresh_max=2, manifest_reset_max=1)


def test_plan_unknown_size_is_single_no_resume():
    plan = plan_transfer(RemoteInfo(None, None, False), SETTINGS,
                         existing=None, url_origin=None)
    assert plan.mode is TransferMode.SINGLE_NO_RESUME and plan.manifest is None


def test_plan_no_range_support_is_single_no_resume():
    plan = plan_transfer(RemoteInfo(10**9, '"e"', False), SETTINGS,
                         existing=None, url_origin=None)
    assert plan.mode is TransferMode.SINGLE_NO_RESUME


def test_plan_small_file_is_single_resumable_with_one_segment():
    plan = plan_transfer(RemoteInfo(10 * 1024 * 1024, '"e"', True), SETTINGS,
                         existing=None, url_origin="o")
    assert plan.mode is TransferMode.SINGLE
    assert plan.manifest is not None and len(plan.manifest.segments) == 1
    assert plan.manifest.url_origin == "o"


def test_plan_segments_one_is_single_resumable():
    s = TransferSettings(segments=1, segment_min_bytes=1, max_connections=12,
                         partial_max_age_hours=0, link_refresh_max=2, manifest_reset_max=1)
    plan = plan_transfer(RemoteInfo(10**9, None, True), s, existing=None, url_origin=None)
    assert plan.mode is TransferMode.SINGLE and len(plan.manifest.segments) == 1


def test_plan_segmented_count_limited_by_min_segment_size():
    # 100 MB / 32 MB min -> at most 3 segments even though 4 requested
    plan = plan_transfer(RemoteInfo(100 * 1024 * 1024, '"e"', True), SETTINGS,
                         existing=None, url_origin=None)
    assert plan.mode is TransferMode.SEGMENTED and len(plan.manifest.segments) == 3


def test_plan_reuses_existing_manifest():
    existing = TransferManifest.plan(10**9, 4, etag='"e"')
    existing.segments[0].done = 5
    plan = plan_transfer(RemoteInfo(10**9, '"e"', True), SETTINGS,
                         existing=existing, url_origin=None)
    assert plan.manifest is existing and plan.mode is TransferMode.SEGMENTED


def test_plan_existing_single_segment_manifest_stays_single():
    existing = TransferManifest.plan(10**9, 1, etag=None)
    plan = plan_transfer(RemoteInfo(10**9, None, True), SETTINGS,
                         existing=existing, url_origin=None)
    assert plan.mode is TransferMode.SINGLE and plan.manifest is existing

class _PM:  # minimal progress manager
    def __init__(self):
        self.completed: list[float] = []
        self.logs: list[str] = []

    def update_task(self, _task, completed=None, advance=0, visible=True):  # pylint: disable=unused-argument
        if completed is not None:
            self.completed.append(completed)

    def update_log(self, *, event, details):  # pylint: disable=unused-argument
        self.logs.append(details)


def _run(server, tmp_path, manifest=None, segments=4, **kwargs):
    temp = tmp_path / "file.bin.temp"
    manifest = manifest or TransferManifest.plan(len(server.data), segments, etag=server.etag)
    pm = _PM()
    dl = SegmentedDownloader(url=server.url, headers={}, temp_path=temp, manifest=manifest,
                             progress_manager=pm, task=0, flush_bytes=256 * 1024, **kwargs)
    return dl.run(), temp, manifest, pm


def _sha_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _assert_prefixes_match(temp, manifest, data):
    on_disk = temp.read_bytes()
    for seg in manifest.segments:
        lo, hi = seg.start, seg.start + seg.done
        assert on_disk[lo:hi] == data[lo:hi]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_segmented_full_transfer_matches_source(range_server, tmp_path):
    outcome, temp, manifest, pm = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.COMPLETE
    assert manifest.complete and temp.stat().st_size == len(range_server.data)
    assert _sha(temp) == hashlib.sha256(range_server.data).hexdigest()
    assert pm.completed and pm.completed[-1] == 100.0
    assert range_server.get_count == 4


def test_segmented_resumes_from_manifest(range_server, tmp_path):
    manifest = TransferManifest.plan(len(range_server.data), 4, etag=range_server.etag)
    temp = tmp_path / "file.bin.temp"
    # Pretend segment 0 is fully on disk and segment 1 half done; write those bytes ourselves.
    with temp.open("wb") as fh:
        fh.truncate(len(range_server.data))
        s0, s1 = manifest.segments[0], manifest.segments[1]
        fh.seek(s0.start)
        fh.write(range_server.data[s0.start:s0.end + 1])
        s0.done = s0.length
        half = s1.length // 2
        fh.seek(s1.start)
        fh.write(range_server.data[s1.start:s1.start + half])
        s1.done = half
    outcome, temp, manifest, _ = _run(range_server, tmp_path, manifest=manifest)
    assert outcome is SegmentedOutcome.COMPLETE
    assert _sha(temp) == hashlib.sha256(range_server.data).hexdigest()
    assert range_server.get_count == 3     # segment 0 never re-fetched


def test_segmented_falls_back_when_server_ignores_range(range_server, tmp_path):
    range_server.ignore_range = True
    outcome, _, manifest, _ = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.RANGE_UNSUPPORTED
    assert manifest.bytes_done == 0      # nothing trusted from a 200 body


def test_segmented_403_requests_link_refresh_and_keeps_progress(range_server, tmp_path):
    range_server.forbid_from_request = 3        # first two segment GETs succeed, rest 403
    cancel = threading.Event()
    outcome, temp, manifest, _ = _run(range_server, tmp_path, cancel_event=cancel)
    assert outcome is SegmentedOutcome.NEEDS_REFRESH
    assert not cancel.is_set()
    _assert_prefixes_match(temp, manifest, range_server.data)
    saved = load_manifest(manifest_path(temp))
    assert saved is not None and saved.bytes_done == manifest.bytes_done > 0
    # second run with a "fresh" URL completes from where it left off
    range_server.forbid_from_request = None
    range_server.get_count = 0
    outcome2, temp, manifest, _ = _run(range_server, tmp_path, manifest=saved)
    assert outcome2 is SegmentedOutcome.COMPLETE and _sha(temp) == _sha_of(range_server.data)


def test_segmented_mid_stream_abort_is_retryable_and_resumable(range_server, tmp_path):
    range_server.abort_once_after = 300_000
    outcome, temp, manifest, _ = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.RETRYABLE
    _assert_prefixes_match(temp, manifest, range_server.data)
    saved = load_manifest(manifest_path(temp))
    assert saved is not None and 0 < saved.bytes_done < len(range_server.data)
    assert any(0 < s.done < s.length for s in saved.segments)   # partial bytes persisted
    incomplete = sum(1 for s in saved.segments if not s.complete)
    range_server.get_count = 0
    outcome2, temp, _, _ = _run(range_server, tmp_path, manifest=saved)
    assert range_server.get_count == incomplete
    assert outcome2 is SegmentedOutcome.COMPLETE and _sha(temp) == _sha_of(range_server.data)


def test_segmented_cancel_leaves_resumable_manifest(range_server, tmp_path):
    cancel = threading.Event()
    cancel.set()                                   # cancelled before the first chunk
    outcome, temp, manifest, _ = _run(range_server, tmp_path, cancel_event=cancel)
    assert outcome is SegmentedOutcome.CANCELLED
    _assert_prefixes_match(temp, manifest, range_server.data)
    saved = load_manifest(manifest_path(temp))
    assert saved is not None and saved.bytes_done == 0
    assert temp.stat().st_size == len(range_server.data)


def test_segmented_respects_governor_cap(range_server, tmp_path):
    gov = ConnectionGovernor(2)
    outcome, _, _, _ = _run(range_server, tmp_path, governor=gov)
    assert outcome is SegmentedOutcome.COMPLETE
    assert range_server.peak_in_flight <= 2


def test_segmented_disk_error_is_terminal_and_keeps_manifest(range_server, tmp_path, monkeypatch):
    import src.downloaders.segmented_download as mod  # pylint: disable=import-outside-toplevel

    def boom(*_a, **_k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(mod.os, "pwrite", boom)
    outcome, temp, manifest, _ = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.TERMINAL
    assert manifest_path(temp).exists()
    _assert_prefixes_match(temp, manifest, range_server.data)


def test_segmented_416_marks_manifest_invalid(range_server, tmp_path):
    # Manifest claims the file is 10 MB larger than the server's object: the
    # second segment starts past EOF (server answers 416) and the first gets a
    # Content-Range that disagrees with what it asked for. Both are manifest
    # errors, never silently accepted.
    manifest = TransferManifest.plan(len(range_server.data) + 10_000_000, 2, etag=range_server.etag)
    outcome, _, _, _ = _run(range_server, tmp_path, manifest=manifest)
    assert outcome is SegmentedOutcome.MANIFEST_INVALID


def test_segmented_206_with_different_etag_is_manifest_invalid(range_server, tmp_path):
    manifest = TransferManifest.plan(len(range_server.data), 4, etag='"some-other-object"')
    outcome, _, manifest, _ = _run(range_server, tmp_path, manifest=manifest)
    assert outcome is SegmentedOutcome.MANIFEST_INVALID
    assert manifest.bytes_done == 0                    # nothing written from the wrong object


def test_segmented_weak_etag_of_same_value_is_accepted(range_server, tmp_path):
    manifest = TransferManifest.plan(len(range_server.data), 4, etag='W/"test-etag-1"')
    outcome, _, _, _ = _run(range_server, tmp_path, manifest=manifest)
    assert outcome is SegmentedOutcome.COMPLETE


def test_segmented_records_last_http_error(range_server, tmp_path):
    range_server.fail_status_from_request = 1
    temp = tmp_path / "file.bin.temp"
    manifest = TransferManifest.plan(len(range_server.data), 4, etag=range_server.etag)
    dl = SegmentedDownloader(url=range_server.url, headers={}, temp_path=temp, manifest=manifest,
                             progress_manager=_PM(), task=0)
    assert dl.run() is SegmentedOutcome.RETRYABLE
    assert dl.last_error is not None and dl.last_error.response.status_code == 503


def test_segmented_short_pwrite_still_writes_every_byte(range_server, tmp_path, monkeypatch):
    real_pwrite = os.pwrite

    def short(fd, data, offset):
        return real_pwrite(fd, bytes(data[:1000]), offset)
    monkeypatch.setattr(os, "pwrite", short)
    outcome, temp, _, _ = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.COMPLETE
    assert _sha(temp) == _sha_of(range_server.data)


def test_segmented_zero_byte_pwrite_is_terminal(range_server, tmp_path, monkeypatch):
    monkeypatch.setattr(os, "pwrite", lambda *_a: 0)
    outcome, _, _, _ = _run(range_server, tmp_path)
    assert outcome is SegmentedOutcome.TERMINAL


def test_segmented_final_flush_failure_is_terminal_and_closes_fd(range_server, tmp_path,
                                                                 monkeypatch):
    import src.downloaders.segmented_download as mod  # pylint: disable=import-outside-toplevel

    real_save = mod.save_manifest

    def flaky(manifest, path):
        if threading.current_thread() is threading.main_thread():   # only the final flush
            raise OSError(28, "No space left on device")
        real_save(manifest, path)
    monkeypatch.setattr(mod, "save_manifest", flaky)
    temp = tmp_path / "file.bin.temp"
    manifest = TransferManifest.plan(len(range_server.data), 4, etag=range_server.etag)
    dl = SegmentedDownloader(url=range_server.url, headers={}, temp_path=temp, manifest=manifest,
                             progress_manager=_PM(), task=0, flush_bytes=256 * 1024)
    assert dl.run() is SegmentedOutcome.TERMINAL
    assert dl._fd is None  # pylint: disable=protected-access


def test_segmented_missing_temp_with_progress_is_manifest_invalid(range_server, tmp_path):
    manifest = TransferManifest.plan(len(range_server.data), 4, etag=range_server.etag)
    manifest.segments[0].done = 1000          # claims progress, but no temp file exists
    outcome, _, _, _ = _run(range_server, tmp_path, manifest=manifest)
    assert outcome is SegmentedOutcome.MANIFEST_INVALID
    assert range_server.get_count == 0         # nothing fetched on top of missing data
