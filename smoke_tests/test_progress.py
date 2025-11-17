"""Smoke tests covering download progress reporting helpers."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Iterable, List
from unittest.mock import patch

from src.downloaders import download_utils


class _FakeRaw:  # pylint: disable=too-few-public-methods
    """Minimal raw stream stub exposing ``length_remaining``."""

    def __init__(self, length_remaining: int | None = None) -> None:
        self.length_remaining = length_remaining


class FakeResponse:  # pylint: disable=too-few-public-methods
    """Test double replicating the ``requests.Response`` surface we rely on."""

    def __init__(self, chunks: Iterable[bytes], headers: dict[str, str] | None = None, raw_remaining: int | None = None) -> None:
        self._chunks: List[bytes] = list(chunks)
        self.headers = headers or {}
        self.raw = _FakeRaw(raw_remaining)

    def iter_content(self, chunk_size: int | None = None):  # noqa: D401 matching ``requests`` API
        """Yield the pre-defined chunks, ignoring ``chunk_size`` for determinism."""
        for chunk in self._chunks:
            yield chunk


class FakeManager:  # pylint: disable=too-few-public-methods
    """Collect task updates triggered by ``save_file_with_progress``."""

    def __init__(self) -> None:
        self.history: list[float | None] = []

    def update_task(self, task_id: int, completed: float | None = None, advance: int = 0, *, visible: bool = True) -> None:
        # We store both absolute and incremental updates so callers can inspect behaviour.
        self.history.append(completed if completed is not None else float(advance))

    def update_log(self, **_: object) -> None:  # pragma: no cover - not needed in smoke tests
        return


class ProgressSmokeTests(unittest.TestCase):
    """Exercise happy-path progress flows without hitting the network."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self.destination = Path(self._tmp_dir.name) / "sample.bin"

    def test_known_length_stream_reports_percentage(self) -> None:
        response = FakeResponse([b"a" * 5] * 4, headers={"Content-Length": "20"})
        manager = FakeManager()

        result = download_utils.save_file_with_progress(
            response,
            str(self.destination),
            task=1,
            progress_manager=manager,
        )

        self.assertFalse(result)
        self.assertTrue(self.destination.exists())
        # Expect intermediate updates and a final completion update.
        self.assertGreater(len(manager.history), 1)
        self.assertEqual(manager.history[-1], 100)
        self.assertTrue(all(0 <= value <= 100 for value in manager.history if value is not None))

    def test_unknown_length_falls_back_to_estimator(self) -> None:
        response = FakeResponse([b"b" * 3] * 8)
        manager = FakeManager()

        result = download_utils.save_file_with_progress(
            response,
            str(self.destination),
            task=7,
            progress_manager=manager,
        )

        self.assertFalse(result)
        self.assertTrue(self.destination.exists())
        self.assertGreater(len(manager.history), 1)
        self.assertEqual(manager.history[-1], 100)
        # The estimator should move forward before completion.
        self.assertGreater(max(manager.history[:-1]), 0)

    def test_head_fallback_integrates_mid_stream_length(self) -> None:
        chunks = [b"c" * 5] * 6  # 30 bytes total
        manager = FakeManager()

        def _delayed_head(_: str, *, timeout: float = 5.0) -> int | None:  # noqa: D401
            del timeout
            time.sleep(0.05)
            return 30

        response = FakeResponse(chunks)
        with patch.object(download_utils, "_head_content_length", side_effect=_delayed_head) as mocked_head:
            result = download_utils.save_file_with_progress(
                response,
                str(self.destination),
                task=2,
                progress_manager=manager,
                download_url="https://example.test/resource",
            )

        self.assertFalse(result)
        self.assertTrue(self.destination.exists())
        mocked_head.assert_called_once()
        # Expect at least one non-zero progress event prior to completion and a final 100% update.
        self.assertGreater(len(manager.history), 1)
        self.assertEqual(manager.history[-1], 100)
        self.assertNotEqual(manager.history[0], 100)


if __name__ == "__main__":
    unittest.main()
