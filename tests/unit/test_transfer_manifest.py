# tests/unit/test_transfer_manifest.py
"""Manifest: segment math, atomic round-trip, validation, discard."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from src.downloaders.transfer_manifest import (
    MANIFEST_VERSION,
    TransferManifest,
    discard_partial,
    load_manifest,
    manifest_matches_remote,
    manifest_path,
    save_manifest,
)


@pytest.mark.parametrize(("size", "n"), [(10, 4), (1000, 3), (1024 * 1024 + 1, 16), (7, 7), (5, 1)])
def test_plan_covers_range_exactly_without_gaps_or_overlap(size, n):
    manifest = TransferManifest.plan(size, n, etag='"e"')
    segs = manifest.segments
    assert len(segs) == n
    assert segs[0].start == 0
    assert segs[-1].end == size - 1
    for prev, cur in zip(segs, segs[1:]):
        assert cur.start == prev.end + 1
    assert sum(s.length for s in segs) == size
    assert all(s.done == 0 for s in segs)
    assert manifest.bytes_done == 0 and not manifest.complete


def test_segment_progress_properties():
    seg = TransferManifest.plan(100, 2, etag=None).segments[1]   # 50..99
    assert (seg.start, seg.end, seg.length) == (50, 99, 50)
    seg.done = 20
    assert seg.remaining == 30 and seg.next_offset == 70 and not seg.complete
    seg.done = 50
    assert seg.complete and seg.remaining == 0


def test_save_and_load_round_trip_is_atomic(tmp_path: Path):
    temp = tmp_path / "video.temp"
    path = manifest_path(temp)
    assert path == tmp_path / "video.temp.parts"
    manifest = TransferManifest.plan(1000, 4, etag='"abc"', url_origin="https://bunkr.cr/f/x")
    manifest.segments[1].done = 120
    save_manifest(manifest, path)
    assert not (tmp_path / "video.temp.parts.tmp").exists()
    loaded = load_manifest(path)
    assert loaded is not None
    assert loaded.size == 1000
    assert loaded.etag == '"abc"'
    assert loaded.url_origin == "https://bunkr.cr/f/x"
    assert [s.done for s in loaded.segments] == [0, 120, 0, 0]
    assert json.loads(path.read_text())["version"] == MANIFEST_VERSION


def test_load_rejects_missing_malformed_and_wrong_version(tmp_path: Path):
    path = tmp_path / "x.temp.parts"
    assert load_manifest(path) is None
    path.write_text("{not json")
    assert load_manifest(path) is None
    path.write_text(json.dumps({"version": 99, "size": 1, "etag": None, "segments": []}))
    assert load_manifest(path) is None
    path.write_text(json.dumps({"version": 1, "size": 1}))       # missing segments
    assert load_manifest(path) is None
    path.write_text("[]")                                         # valid JSON, not an object
    assert load_manifest(path) is None
    path.write_text('"x"')
    assert load_manifest(path) is None


def test_manifest_mismatch_on_size():
    manifest = TransferManifest.plan(1000, 2, etag='"a"')
    assert manifest_matches_remote(manifest, size=1000, etag='"a"')
    assert not manifest_matches_remote(manifest, size=1001, etag='"a"')
    assert not manifest_matches_remote(manifest, size=None, etag='"a"')


def test_manifest_etag_rules():
    manifest = TransferManifest.plan(1000, 2, etag='"a"')
    # remote has no ETag -> size only
    assert manifest_matches_remote(manifest, size=1000, etag=None)
    assert not manifest_matches_remote(manifest, size=1000, etag='"b"')
    assert manifest_matches_remote(manifest, size=1000, etag='W/"a"')    # weak compares by value
    no_etag = TransferManifest.plan(1000, 2, etag=None)
    # local has no ETag -> size only
    assert manifest_matches_remote(no_etag, size=1000, etag='"zzz"')


def test_discard_partial_removes_both_and_ignores_missing(tmp_path: Path):
    temp = tmp_path / "f.temp"
    temp.write_bytes(b"xx")
    manifest_path(temp).write_text("{}")
    discard_partial(temp)
    assert not temp.exists() and not manifest_path(temp).exists()
    discard_partial(temp)   # no raise


def test_valid_dict_loads_back(tmp_path: Path):
    path = tmp_path / "ok.temp.parts"
    path.write_text(json.dumps(TransferManifest.plan(100, 2, etag='"a"').to_dict()))
    assert load_manifest(path) is not None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["segments"][0].update(done=-1),                  # negative done
        lambda d: d["segments"][0].update(done=51),                  # done > length (50)
        lambda d: d["segments"][1].update(start=51),                 # gap between segments
        lambda d: d["segments"][-1].update(end=98),                  # last end != size - 1
        lambda d: d.update(etag=123),                                # non-string etag
        lambda d: d.update(size=-1),                                 # negative size
    ],
)
def test_structurally_invalid_manifest_loads_as_none(tmp_path: Path, mutate):
    data = TransferManifest.plan(100, 2, etag='"a"').to_dict()
    mutate(data)
    path = tmp_path / "bad.temp.parts"
    path.write_text(json.dumps(data))
    assert load_manifest(path) is None


def test_concurrent_saves_leave_valid_manifest_and_no_tmp(tmp_path: Path):
    path = tmp_path / "race.temp.parts"
    manifest = TransferManifest.plan(1000, 4, etag='"abc"')
    errors: list[OSError] = []

    def worker():
        try:
            for _ in range(50):
                save_manifest(manifest, path)
        except OSError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    loaded = load_manifest(path)
    assert loaded is not None and loaded.size == 1000
    assert not (tmp_path / "race.temp.parts.tmp").exists()


def test_failed_replace_removes_tmp_and_reraises(tmp_path: Path, monkeypatch):
    path = tmp_path / "f.temp.parts"

    def boom(_src, _dst):
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        save_manifest(TransferManifest.plan(10, 2, etag=None), path)
    assert not (tmp_path / "f.temp.parts.tmp").exists()
    assert not path.exists()


def test_temp_path_for_appends_to_the_full_name(tmp_path):
    # pylint: disable-next=import-outside-toplevel
    from src.downloaders.transfer_manifest import temp_path_for

    assert temp_path_for(tmp_path / "a.mp4") == tmp_path / "a.mp4.temp"
    assert temp_path_for(str(tmp_path / "a.mp4")) == tmp_path / "a.mp4.temp"
    assert temp_path_for(tmp_path / "a.mp4") != temp_path_for(tmp_path / "a.mkv")
    assert temp_path_for(tmp_path / "noext") == tmp_path / "noext.temp"


def test_discard_partial_tolerates_any_oserror(tmp_path, monkeypatch):
    parts_of = manifest_path
    temp = tmp_path / "f.bin.temp"
    temp.write_bytes(b"x")
    parts_of(temp).write_text("{}")
    real_unlink = Path.unlink

    def deny(self, *args, **kwargs):
        if self.name.endswith(".temp"):
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", deny)
    discard_partial(temp)                      # must not raise
    assert temp.exists() and not parts_of(temp).exists()
