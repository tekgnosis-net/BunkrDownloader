"""Regression tests for :func:`save_file_with_progress` + ``_finalise_download``."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable
from unittest.mock import patch

import pytest
from requests.exceptions import ChunkedEncodingError

from src.downloaders import download_utils
from src.downloaders.download_utils import (
    DownloadOutcome,
    _finalise_download,
    save_file_with_progress,
)


class _FakeRaw:  # pylint: disable=too-few-public-methods
    def __init__(self, length_remaining: int | None = None) -> None:
        self.length_remaining = length_remaining


class FakeResponse:  # pylint: disable=too-few-public-methods
    """Minimal stand-in for ``requests.Response`` used by tests."""

    def __init__(
        self,
        chunks: Iterable[bytes],
        headers: dict[str, str] | None = None,
        raw_remaining: int | None = None,
        raises: type[Exception] | None = None,
    ) -> None:
        self._chunks = list(chunks)
        self.headers = headers or {}
        self.raw = _FakeRaw(raw_remaining)
        self._raises = raises

    def iter_content(self, chunk_size: int | None = None):
        """Stream pre-set chunks, then optionally raise to simulate a mid-stream error."""
        del chunk_size
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk
        if self._raises:
            raise self._raises("simulated mid-stream failure")


def test_save_file_with_progress_known_length_completes(
    fake_live_manager, tmp_path: Path,
) -> None:
    """Happy path with a Content-Length header resolves to SUCCESS and 100%."""

    chunks = [b"a" * 16, b"b" * 16]
    total = sum(len(c) for c in chunks)
    response = FakeResponse(chunks, headers={"Content-Length": str(total)})
    dest = tmp_path / "file.bin"

    outcome = save_file_with_progress(
        response, str(dest), task=0, progress_manager=fake_live_manager,
    )

    assert outcome is DownloadOutcome.SUCCESS
    # Final update lands on completed=100
    final_updates = [u for _, u in fake_live_manager.task_updates if u["completed"] == 100]
    assert final_updates, "expected a completed=100 update on success"
    assert dest.exists()


def test_save_file_with_progress_chunked_encoding_hides_task(
    fake_live_manager, tmp_path: Path,
) -> None:
    """ChunkedEncodingError must terminate the task visibly rather than stalling."""

    response = FakeResponse(
        [b"x" * 8],
        headers={"Content-Length": "100"},
        raises=ChunkedEncodingError,
    )
    dest = tmp_path / "chunked.bin"

    outcome = save_file_with_progress(
        response, str(dest), task=0, progress_manager=fake_live_manager,
    )

    assert outcome is DownloadOutcome.RETRYABLE_FAILURE
    hidden = [u for _, u in fake_live_manager.task_updates if u["visible"] is False]
    assert hidden, "task must be marked invisible after ChunkedEncodingError"


def test_finalise_download_osexception_marks_task_invisible(
    fake_live_manager, tmp_path: Path,
) -> None:
    """Regression for the 99% stall: rename failure must hide the task."""

    temp_path = tmp_path / "file.temp"
    temp_path.write_bytes(b"x" * 16)
    # Use a destination path pointing into a missing directory to force an OSError.
    final_path = str(tmp_path / "missing-subdir" / "file.bin")

    outcome = _finalise_download(
        file_size=16,
        total_downloaded=16,
        temp_path=temp_path,
        final_path=final_path,
        progress_manager=fake_live_manager,
        task=0,
    )

    assert outcome is DownloadOutcome.RETRYABLE_FAILURE
    hidden = [u for _, u in fake_live_manager.task_updates if u["visible"] is False]
    assert hidden, "task must be hidden when shutil.move fails"


def test_save_file_with_progress_unknown_length_promotes_head_result(
    fake_live_manager, tmp_path: Path,
) -> None:
    """Late HEAD resolves real size → final completed lands at 100."""

    chunks = [b"a" * 32, b"b" * 32]
    total = sum(len(c) for c in chunks)
    response = FakeResponse(chunks)  # no Content-Length, no raw_remaining
    dest = tmp_path / "late-head.bin"

    with patch.object(download_utils, "_head_content_length", return_value=total):
        outcome = save_file_with_progress(
            response,
            str(dest),
            task=0,
            progress_manager=fake_live_manager,
            download_url="https://example/file",
        )

    assert outcome is DownloadOutcome.SUCCESS
    final_updates = [u for _, u in fake_live_manager.task_updates if u["completed"] == 100]
    assert final_updates, "expected completed=100 even when Content-Length arrives late"


@pytest.mark.parametrize(
    "file_size, downloaded, expected",
    [
        (None, 0, DownloadOutcome.SUCCESS),  # zero-byte unknown-length file
        (10, 10, DownloadOutcome.SUCCESS),   # matched known length
        (20, 10, DownloadOutcome.RETRYABLE_FAILURE),  # short read
    ],
)
def test_finalise_download_outcome_matrix(
    fake_live_manager, tmp_path: Path, file_size, downloaded, expected,
) -> None:
    """Comprehensive matrix covering the three ``_finalise_download`` branches."""

    temp_path = tmp_path / "file.temp"
    temp_path.write_bytes(b"")
    final_path = str(tmp_path / "final.bin")

    outcome = _finalise_download(
        file_size=file_size,
        total_downloaded=downloaded,
        temp_path=temp_path,
        final_path=final_path,
        progress_manager=fake_live_manager,
        task=0,
    )
    assert outcome is expected


def test_save_file_resumes_from_offset_and_updates_manifest(tmp_path, fake_live_manager):
    """A 206 continuation writes at the offset and removes the manifest on success."""
    # pylint: disable-next=import-outside-toplevel
    from src.downloaders.transfer_manifest import (
        TransferManifest, manifest_path, temp_path_for,
    )

    final = tmp_path / "f.bin"
    temp = temp_path_for(final)
    temp.write_bytes(b"A" * 10 + b"\0" * 10)           # 10 good bytes, pre-sized to 20
    manifest = TransferManifest.plan(20, 1, etag=None)
    manifest.segments[0].done = 10
    response = FakeResponse(
        chunks=[b"B" * 5, b"B" * 5], headers={"Content-Length": "10"},
    )
    outcome = save_file_with_progress(
        response, str(final), 0, fake_live_manager,
        resume_from=10, manifest=manifest,
    )
    assert outcome is DownloadOutcome.SUCCESS
    assert final.read_bytes() == b"A" * 10 + b"B" * 10
    assert not manifest_path(temp).exists()            # removed on success


def test_save_file_partial_keeps_manifest_progress(tmp_path, fake_live_manager):
    """An interrupted stream persists its byte count for the next attempt."""
    # pylint: disable-next=import-outside-toplevel
    from src.downloaders.transfer_manifest import (
        TransferManifest, load_manifest, manifest_path, temp_path_for,
    )

    final = tmp_path / "g.bin"
    temp = temp_path_for(final)
    manifest = TransferManifest.plan(30, 1, etag='"e"')
    response = FakeResponse(
        chunks=[b"x" * 10, ChunkedEncodingError("cut")],
        headers={"Content-Length": "30"},
    )
    outcome = save_file_with_progress(response, str(final), 0, fake_live_manager, manifest=manifest)
    assert outcome is DownloadOutcome.RETRYABLE_FAILURE
    saved = load_manifest(manifest_path(temp))
    assert saved is not None and saved.segments[0].done == 10
    assert temp.exists()


def test_finalise_succeeds_when_only_the_manifest_delete_fails(
    tmp_path: Path, fake_live_manager, monkeypatch,
) -> None:
    """The rename is what matters: a stuck .parts must not turn SUCCESS into a retry."""

    temp = tmp_path / "f.bin.temp"
    temp.write_bytes(b"x" * 8)
    parts = tmp_path / "f.bin.temp.parts"
    parts.write_text("{}")
    real_unlink = Path.unlink

    def deny(self, *args, **kwargs):
        if self.name.endswith(".parts"):
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", deny)
    outcome = _finalise_download(
        file_size=8, total_downloaded=8, temp_path=temp,
        final_path=str(tmp_path / "f.bin"), progress_manager=fake_live_manager, task=0,
        manifest_file=parts,
    )
    assert outcome is DownloadOutcome.SUCCESS and (tmp_path / "f.bin").exists()


def test_single_stream_survives_manifest_save_errors(
    tmp_path: Path, fake_live_manager, monkeypatch,
) -> None:
    """A manifest that cannot be written costs resumability, not the download."""
    # pylint: disable-next=import-outside-toplevel
    from src.downloaders.transfer_manifest import TransferManifest

    def broken(*_args, **_kwargs):
        raise OSError(5, "Input/output error")
    monkeypatch.setattr(download_utils, "save_manifest", broken)
    monkeypatch.setattr(download_utils, "MANIFEST_FLUSH_BYTES", 8)
    manifest = TransferManifest.plan(32, 1, etag=None)
    response = FakeResponse([b"z" * 8] * 4, headers={"Content-Length": "32"})
    final = tmp_path / "s.bin"
    outcome = save_file_with_progress(response, str(final), 0, fake_live_manager,
                                      manifest=manifest)
    assert outcome is DownloadOutcome.SUCCESS and final.read_bytes() == b"z" * 32


def test_single_stream_stops_between_chunks_when_cancelled(
    tmp_path: Path, fake_live_manager,
) -> None:
    """The cancel flag is honoured between chunks and the progress is persisted."""
    # pylint: disable-next=import-outside-toplevel
    import threading
    # pylint: disable-next=import-outside-toplevel
    from src.downloaders.transfer_manifest import (
        TransferManifest, load_manifest, manifest_path, temp_path_for,
    )

    cancel = threading.Event()
    manifest = TransferManifest.plan(40, 1, etag=None)

    class _Cancelling(FakeResponse):  # pylint: disable=too-few-public-methods
        def iter_content(self, chunk_size=None):
            for index, chunk in enumerate(super().iter_content(chunk_size)):
                if index == 2:
                    cancel.set()
                yield chunk
    response = _Cancelling([b"c" * 10] * 4, headers={"Content-Length": "40"})
    final = tmp_path / "c.bin"
    outcome = save_file_with_progress(response, str(final), 0, fake_live_manager,
                                      manifest=manifest, cancel_event=cancel)
    assert outcome is DownloadOutcome.RETRYABLE_FAILURE and not final.exists()
    saved = load_manifest(manifest_path(temp_path_for(final)))
    assert saved is not None and saved.segments[0].done == 20
