"""Shared pytest fixtures for BunkrDownloader tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.config import NetworkContext, SessionInfo


@pytest.fixture
def network_context() -> NetworkContext:
    """Return an isolated NetworkContext for unit tests."""

    return NetworkContext(
        status_page="https://status.example/",
        bunkr_api="https://api.example/api/vs",
        fallback_domain="example.cr",
        user_agent="test-agent/1.0",
        download_referer="https://referer.example/",
    )


@pytest.fixture
def session_info(network_context: NetworkContext, tmp_path: Path) -> SessionInfo:
    """Return a SessionInfo pointing at a tmp download directory."""

    return SessionInfo(
        args=None,
        bunkr_status={},
        download_path=str(tmp_path),
        network=network_context,
    )


class FakeLiveManager:
    """In-memory stand-in for LiveManager used by downloader unit tests."""

    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []
        self.task_updates: list[tuple[int, dict[str, Any]]] = []
        self.overall: dict[str, Any] | None = None
        self._next_task_id = 0

    def add_overall_task(self, description: str, num_tasks: int) -> None:
        self.overall = {"description": description, "total": num_tasks, "completed": 0}

    def add_task(self, current_task: int = 0, total: int = 100) -> int:
        task_id = self._next_task_id
        self._next_task_id += 1
        return task_id

    def update_task(
        self,
        task_id: int,
        completed: int | None = None,
        advance: int = 0,
        *,
        visible: bool = True,
    ) -> None:
        self.task_updates.append(
            (task_id, {"completed": completed, "advance": advance, "visible": visible}),
        )

    def update_log(self, *, event: str, details: str) -> None:
        self.logs.append((event, details))

    def log_debug(self, *, event: str, details: str) -> None:  # pragma: no cover - trivial
        pass

    def update_maintenance(self, **kwargs: Any) -> None:  # pragma: no cover - trivial
        self.logs.append((kwargs.get("event", ""), kwargs.get("details", "")))

    def stop(self) -> None:  # pragma: no cover - trivial
        pass


@pytest.fixture
def fake_live_manager() -> FakeLiveManager:
    """Expose a FakeLiveManager to tests that exercise the downloader helpers."""

    return FakeLiveManager()
