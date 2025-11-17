"""Smoke tests covering download progress reporting helpers."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from contextlib import ExitStack
from typing import Iterable, List
from unittest.mock import patch

from src.downloaders import download_utils


class _FakeRaw:  # pylint: disable=too-few-public-methods
    """Minimal raw stream stub exposing ``length_remaining``."""

    def __init__(self, length_remaining: int | None = None) -> None:
        self.length_remaining = length_remaining


class FakeResponse:  # pylint: disable=too-few-public-methods
    """Test double replicating the ``requests.Response`` surface we rely on."""

    def __init__(
        self,
        chunks: Iterable[bytes],
        headers: dict[str, str] | None = None,
        raw_remaining: int | None = None,
    ) -> None:
        self._chunks: List[bytes] = list(chunks)
        self.headers = headers or {}
        self.raw = _FakeRaw(raw_remaining)

    def iter_content(self, chunk_size: int | None = None):  # noqa: D401 matching ``requests`` API
        """Yield the pre-defined chunks, ignoring ``chunk_size`` for determinism."""
        del chunk_size
        yield from self._chunks


class FakeManager:  # pylint: disable=too-few-public-methods
    """Collect task updates triggered by ``save_file_with_progress``."""

    def __init__(self) -> None:
        self.history: list[float | None] = []

    def update_task(
        self,
        _task_id: int,
        completed: float | None = None,
        advance: int = 0,
        *,
        visible: bool = True,
    ) -> None:
        """Capture task updates so tests can assert on progression."""
        # We store both absolute and incremental updates so callers can inspect behaviour.
        del visible
        self.history.append(completed if completed is not None else float(advance))

    def update_log(self, **_: object) -> None:  # pragma: no cover - not needed in smoke tests
        """Ignore log updates; the smoke tests only validate progress calls."""
        return


class ProgressSmokeTests(unittest.TestCase):
    """Exercise happy-path progress flows without hitting the network."""

    def setUp(self) -> None:
        """Prepare a temporary directory for artefact checks."""
        self._exit_stack = ExitStack()
        self.addCleanup(self._exit_stack.close)
        tmp_dir = self._exit_stack.enter_context(tempfile.TemporaryDirectory())
        self.destination = Path(tmp_dir.name) / "sample.bin"

    def test_known_length_stream_reports_percentage(self) -> None:
        """Streams with a length header should emit percentage progress."""
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
        self.assertTrue(
            all(0 <= value <= 100 for value in manager.history if value is not None)
        )

    def test_unknown_length_falls_back_to_estimator(self) -> None:
        """Streams without length should still progress via estimator."""
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
        """Delayed HEAD responses should inform later progress updates."""
        chunks = [b"c" * 5] * 6  # 30 bytes total
        manager = FakeManager()

        def _delayed_head(_: str, *, timeout: float = 5.0) -> int | None:
            """Simulate a slow HEAD request returning a length."""
            del timeout
            time.sleep(0.05)
            return 30

        response = FakeResponse(chunks)
        with patch.object(
            download_utils,
            "_head_content_length",
            side_effect=_delayed_head,
        ) as mocked_head:
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
