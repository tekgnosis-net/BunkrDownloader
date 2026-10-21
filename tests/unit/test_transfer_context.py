"""Per-job TransferContext: a real connection cap and a cancel flag (I1 + I3)."""

# pylint: disable=missing-function-docstring,protected-access
from __future__ import annotations

import hashlib
import threading
import time
from argparse import Namespace
from unittest.mock import patch

from src.config import DownloadInfo, NetworkContext, SessionInfo, resolve_transfer_settings
from src.downloaders.connection_governor import ConnectionGovernor
from src.downloaders.download_utils import DownloadOutcome
from src.downloaders.media_downloader import MediaDownloader
from src.downloaders.transfer_context import TransferContext, make_transfer_context
from src.downloaders.transfer_manifest import load_manifest, manifest_path, temp_path_for


def _args(**overrides) -> Namespace:
    args = Namespace(skip_status_check=True, status_cache_ttl=60, maintenance_strategy="skip",
                     segments=4, segment_min_size_mb=1, max_connections=12,
                     partial_max_age_hours=0, max_workers=1)
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _dl(live, tmp_path, url, *, ctx=None, filename="file.bin", **overrides):
    network = NetworkContext(status_page="https://s.example/", bunkr_api="https://a.example/",
                             fallback_domain="example.cr", user_agent="t/1",
                             download_referer="https://r.example/")
    # A non-empty status map keeps download() from fetching the real status page.
    si = SessionInfo(args=_args(**overrides), bunkr_status={"Cdn": "Operational"},
                     download_path=str(tmp_path), network=network)
    return MediaDownloader(session_info=si,
                           download_info=DownloadInfo(download_link=url, filename=filename, task=0),
                           live_manager=live, retries=3, transfer_context=ctx)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- context factory ---------------------------------------------------------

def test_context_cap_is_max_of_connections_and_workers():
    assert make_transfer_context(_args(max_connections=2, max_workers=5)).governor.limit == 5
    assert make_transfer_context(_args(max_connections=7, max_workers=3)).governor.limit == 7
    assert make_transfer_context(None).governor.limit >= 1


def test_context_uses_callers_cancel_event_and_resolved_settings():
    event = threading.Event()
    ctx = make_transfer_context(_args(segments=2), cancel_event=event)
    assert ctx.cancel_event is event and not ctx.cancelled
    assert ctx.settings == resolve_transfer_settings(_args(segments=2))
    event.set()
    assert ctx.cancelled


def test_each_context_has_its_own_governor():
    first, second = make_transfer_context(_args()), make_transfer_context(_args())
    assert first.governor is not second.governor


# ---- connection cap -----------------------------------------------------------

def test_segmented_job_honours_per_job_cap(range_server, tmp_path, fake_live_manager):
    range_server.chunk_delay = 0.002
    dl = _dl(fake_live_manager, tmp_path, range_server.url, max_connections=2)
    assert dl._ctx.governor.limit == 2
    final = tmp_path / "file.bin"
    assert dl.attempt_download(str(final)) is DownloadOutcome.SUCCESS
    assert range_server.get_count == 4                    # four segments ...
    assert range_server.peak_in_flight <= 2               # ... never more than the cap at once
    assert _sha(final.read_bytes()) == _sha(range_server.data)


def test_concurrent_single_streams_share_the_job_cap(range_server, tmp_path, fake_live_manager):
    range_server.chunk_delay = 0.003                      # ~0.25 s per stream: they would overlap
    ctx = TransferContext(settings=resolve_transfer_settings(_args(segment_min_size_mb=100)),
                          governor=ConnectionGovernor(1))
    outcomes: dict[str, DownloadOutcome] = {}

    def run(name):
        dl = _dl(fake_live_manager, tmp_path, range_server.url, ctx=ctx, filename=name,
                 segment_min_size_mb=100)
        outcomes[name] = dl.attempt_download(str(tmp_path / name))
    threads = [threading.Thread(target=run, args=(name,)) for name in ("a.bin", "b.bin")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert outcomes == {"a.bin": DownloadOutcome.SUCCESS, "b.bin": DownloadOutcome.SUCCESS}
    assert range_server.get_count == 2 and range_server.peak_in_flight == 1
    for name in ("a.bin", "b.bin"):
        assert _sha((tmp_path / name).read_bytes()) == _sha(range_server.data)


def test_single_stream_waits_for_a_free_slot(range_server, tmp_path, fake_live_manager):
    ctx = TransferContext(settings=resolve_transfer_settings(_args(segment_min_size_mb=100)),
                          governor=ConnectionGovernor(1))
    dl = _dl(fake_live_manager, tmp_path, range_server.url, ctx=ctx, segment_min_size_mb=100)
    result: list[DownloadOutcome] = []
    with ctx.governor.slot():                             # someone else holds the only slot
        worker = threading.Thread(
            target=lambda: result.append(dl.attempt_download(str(tmp_path / "file.bin"))))
        worker.start()
        time.sleep(0.5)
        assert worker.is_alive() and range_server.get_count == 0
    worker.join(timeout=10)
    assert result == [DownloadOutcome.SUCCESS] and range_server.get_count == 1


# ---- cancellation ----------------------------------------------------------------

def _cancel_when_progress(live, ctx, threshold: float) -> dict[str, float]:
    """Background thread: set the job's cancel flag once progress passes ``threshold`` %.

    Returns a dict that receives ``at`` (monotonic time of the cancel).
    """
    stamp: dict[str, float] = {}

    def watch():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            done = [u["completed"] for _, u in list(live.task_updates) if u["completed"]]
            if done and max(done) >= threshold:
                stamp["at"] = time.monotonic()
                ctx.cancel_event.set()
                return
            time.sleep(0.002)
    threading.Thread(target=watch, daemon=True).start()
    return stamp


def _run_cancelled(dl):
    """Run ``download()`` recording what ``attempt_download`` returned and when it ended."""
    outcomes = []
    real_attempt = dl.attempt_download

    def attempt(path):
        outcomes.append(real_attempt(path))
        return outcomes[-1]
    with patch.object(dl, "attempt_download", side_effect=attempt):
        failed = dl.download()
    return failed, outcomes, time.monotonic()


def test_cancel_mid_segmented_transfer_stops_and_keeps_resumable_partial(
    range_server, tmp_path, fake_live_manager,
):
    range_server.chunk_delay = 0.01                       # ~0.4 s per segment
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    final = tmp_path / "file.bin"
    stamp = _cancel_when_progress(fake_live_manager, dl._ctx, 10)
    failed, outcomes, finished = _run_cancelled(dl)
    assert outcomes == [DownloadOutcome.RETRYABLE_FAILURE]
    assert failed is None                                 # never queued for the retry pass
    assert not any(e == "Exceeded retry attempts" for e, _ in fake_live_manager.logs)
    assert any(e == "Download stopped" for e, _ in fake_live_manager.logs)
    # Each segment needs ~0.4 s in full; stopping "within a few chunks" is far quicker.
    assert finished - stamp["at"] < 0.3
    saved = load_manifest(manifest_path(temp_path_for(final)))
    assert saved is not None and 0 < saved.bytes_done < len(range_server.data)
    assert not final.exists() and range_server.get_count == 4
    on_disk = temp_path_for(final).read_bytes()
    for seg in saved.segments:                            # the manifest only claims real bytes
        lo, hi = seg.start, seg.start + seg.done
        assert on_disk[lo:hi] == range_server.data[lo:hi]


def test_cancel_mid_single_stream_stops_and_keeps_resumable_partial(
    range_server, tmp_path, fake_live_manager,
):
    range_server.chunk_delay = 0.005                      # ~0.4 s for the whole file
    dl = _dl(fake_live_manager, tmp_path, range_server.url, segment_min_size_mb=100)
    final = tmp_path / "file.bin"
    stamp = _cancel_when_progress(fake_live_manager, dl._ctx, 10)
    failed, outcomes, finished = _run_cancelled(dl)
    assert outcomes == [DownloadOutcome.RETRYABLE_FAILURE] and failed is None
    assert finished - stamp["at"] < 0.3                   # the whole file needs ~0.4 s
    saved = load_manifest(manifest_path(temp_path_for(final)))
    assert saved is not None and 0 < saved.bytes_done < len(range_server.data)
    done = saved.bytes_done
    assert temp_path_for(final).read_bytes()[:done] == range_server.data[:done]
    assert range_server.get_count == 1                    # no retry after the cancel


def test_cancel_returns_promptly(range_server, tmp_path, fake_live_manager):
    range_server.chunk_delay = 0.01
    dl = _dl(fake_live_manager, tmp_path, range_server.url)
    timer = threading.Timer(0.15, dl._ctx.cancel_event.set)
    start = time.monotonic()
    timer.start()
    outcome = dl.attempt_download(str(tmp_path / "file.bin"))
    elapsed = time.monotonic() - start
    timer.join()
    assert outcome is DownloadOutcome.RETRYABLE_FAILURE
    assert elapsed < 0.15 + 1.0             # a full transfer needs ~0.4 s+ per segment
    saved = load_manifest(manifest_path(temp_path_for(tmp_path / "file.bin")))
    assert saved is not None and 0 < saved.bytes_done < len(range_server.data)


def test_backoff_wakes_on_cancel(tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, "https://cdn.example/file.bin")
    threading.Timer(0.1, dl._ctx.cancel_event.set).start()
    start = time.monotonic()
    assert dl._retry_with_backoff(0, event="Retrying download") is False
    assert time.monotonic() - start < 2.0                 # the backoff itself is >= 4 s


def test_cancelled_failure_is_not_queued(tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, "https://cdn.example/file.bin")
    assert dl._handle_failed_download(is_final_attempt=False, cancelled=True) is None
    queued = dl._handle_failed_download(is_final_attempt=False, cancelled=False)
    assert queued is not None and queued["filename"] == "file.bin"


def test_download_skips_entirely_when_already_cancelled(tmp_path, fake_live_manager):
    dl = _dl(fake_live_manager, tmp_path, "https://cdn.example/file.bin")
    dl._ctx.cancel_event.set()
    with patch.object(dl, "attempt_download") as attempt:
        assert dl.download() is None
    attempt.assert_not_called()
