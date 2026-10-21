"""plan_transfer decisions and the SegmentedDownloader against a local range server."""

# pylint: disable=missing-function-docstring,too-many-arguments
from __future__ import annotations

from src.config import TransferSettings
from src.downloaders.remote_probe import RemoteInfo
from src.downloaders.segmented_download import TransferMode, plan_transfer
from src.downloaders.transfer_manifest import TransferManifest

SETTINGS = TransferSettings(segments=4, segment_min_bytes=32 * 1024 * 1024,
                            max_connections=12, partial_max_age_hours=168)


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
                         partial_max_age_hours=0)
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
