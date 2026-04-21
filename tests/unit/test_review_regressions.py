"""Regression guards for the three review findings on PR1.

Each test targets a specific comment so a future refactor that backslides
on the contract surfaces a loud failure with a named test.
"""

# Fake HTTP response doubles are intentionally thin and bs4 is imported
# lazily to keep the test collection fast when the crawler path isn't
# exercised — both patterns are fine in tests.
# pylint: disable=missing-function-docstring,too-few-public-methods,unused-argument,import-outside-toplevel
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from src.crawlers.crawler_utils import get_download_info, get_item_download_link
from src.downloaders import download_utils
from src.web.app import JobEventBroker


@pytest.mark.asyncio
async def test_hello_next_id_matches_events_endpoint_cursor() -> None:
    """The WebSocket hello frame must send the same cursor value as ``/events``.

    ``/events?since=N`` returns envelopes with ``event_id > N`` — if the
    hello frame advertised ``next_event_id`` (one *past* the last delivered
    id), a reconnecting client that echoed it would skip the next event.
    Hence hello uses ``last_event_id``, identical to what HTTP polling
    returns as ``next_id``.
    """

    broker = JobEventBroker()
    broker.bind(asyncio.get_running_loop())
    for i in range(3):
        broker.publish({"type": "log", "event": f"e{i}", "details": ""})

    # HTTP endpoint cursor: max event_id of returned events.
    http_next_id = max(e["event_id"] for e in broker.get_events())

    # Hello frame cursor (what the WS handler emits): last_event_id.
    ws_next_id = broker.last_event_id

    assert ws_next_id == http_next_id, (
        f"cursor semantics mismatch: ws={ws_next_id} http={http_next_id}"
    )
    # And asking /events?since=last_event_id returns nothing new.
    assert broker.get_events(since=ws_next_id) == []


@pytest.mark.asyncio
async def test_get_item_download_link_returns_none_on_api_failure() -> None:
    """Guard against the old ``decrypt_url(None)`` TypeError.

    When ``get_api_response`` can't reach the API (network error, non-200),
    the helper must propagate ``None`` instead of indexing into it.
    """

    with patch(
        "src.crawlers.crawler_utils.get_api_response",
        return_value=None,
    ):
        result = await get_item_download_link("https://bunkr.test/v/abc")
        assert result is None


@pytest.mark.asyncio
async def test_get_download_info_tolerates_missing_link() -> None:
    """``get_download_info`` should return ``(None, filename)`` on API failure."""

    from bs4 import BeautifulSoup

    # Provide a minimal soup that get_item_filename can parse.
    html = (
        '<h1 class="text-subs font-semibold text-base sm:text-lg truncate">foo.bin</h1>'
    )
    soup = BeautifulSoup(html, "html.parser")

    with patch(
        "src.crawlers.crawler_utils.get_api_response",
        return_value=None,
    ):
        link, filename = await get_download_info("https://bunkr.test/v/abc", soup)
        assert link is None
        assert "foo" in filename


def test_head_content_length_uses_supplied_headers() -> None:
    """The HEAD probe must use the caller's headers, not module defaults.

    Without this, a per-job NetworkContext override (custom user-agent or
    referer) would be ignored by the content-length backfill path — some
    CDNs serve different responses based on those headers, which would
    yield an inconsistent content length versus the streaming GET.
    """

    captured: dict[str, dict[str, str]] = {}

    class _FakeResponse:
        status_code = 200
        headers = {"Content-Length": "1234"}

        def raise_for_status(self) -> None:
            return None

    def _fake_head(url, *, headers, timeout, allow_redirects):  # noqa: ARG001
        captured["headers"] = headers
        return _FakeResponse()

    custom = {"User-Agent": "custom-agent/2.0", "Referer": "https://custom/ref"}
    with patch("src.downloaders.download_utils.requests.head", side_effect=_fake_head):
        length = download_utils._head_content_length(  # pylint: disable=protected-access
            "https://cdn.example/file.bin",
            headers=custom,
        )

    assert length == 1234
    assert captured["headers"] == custom


def test_head_content_length_falls_back_to_module_defaults() -> None:
    """Callers that omit ``headers`` keep the pre-PR2 behaviour (module globals)."""

    captured: dict[str, dict[str, str]] = {}

    class _FakeResponse:
        status_code = 200
        headers = {"Content-Length": "42"}

        def raise_for_status(self) -> None:
            return None

    def _fake_head(url, *, headers, timeout, allow_redirects):  # noqa: ARG001
        captured["headers"] = headers
        return _FakeResponse()

    with patch("src.downloaders.download_utils.requests.head", side_effect=_fake_head):
        length = download_utils._head_content_length(  # pylint: disable=protected-access
            "https://cdn.example/file.bin",
        )
    assert length == 42
    # Default path uses the module-level DOWNLOAD_HEADERS dict.
    assert captured["headers"] is download_utils.DOWNLOAD_HEADERS


@pytest.mark.asyncio
async def test_album_unresolved_link_finishes_task_without_download() -> None:
    """When the Bunkr API returns None for an item, the album must not wedge.

    Regression for the Copilot comment on album_downloader.py: a None
    download link used to leave the created task row visible+unfinished
    forever, blocking the overall counter from ever reaching completion.
    """

    from argparse import Namespace
    from bs4 import BeautifulSoup

    from src.config import AlbumInfo, NetworkContext, SessionInfo
    from src.downloaders.album_downloader import AlbumDownloader

    class _StubManager:
        def __init__(self) -> None:
            self.overall: dict = {}
            self.task_updates: list = []
            self.logs: list = []
            self._next = 0

        def add_overall_task(self, description, num_tasks):
            self.overall = {"description": description, "total": num_tasks, "completed": 0}

        def add_task(self, current_task=0, total=100):
            tid = self._next
            self._next += 1
            return tid

        def update_task(self, task_id, completed=None, advance=0, *, visible=True):
            self.task_updates.append(
                (task_id, {"completed": completed, "visible": visible}),
            )

        def update_log(self, *, event, details):
            self.logs.append((event, details))

        def update_maintenance(self, **_):
            pass

    mgr = _StubManager()
    network = NetworkContext(
        status_page="https://status.example/",
        bunkr_api="https://api.example/api/vs",
        fallback_domain="example.cr",
        user_agent="ua/1",
        download_referer="https://ref.example/",
    )
    session_info = SessionInfo(
        args=Namespace(skip_status_check=True),
        bunkr_status={},
        download_path="/tmp",
        network=network,
    )
    downloader = AlbumDownloader(
        session_info=session_info,
        album_info=AlbumInfo(album_id="stub", item_pages=["https://bunkr.test/v/a"]),
        live_manager=mgr,
    )

    soup = BeautifulSoup(
        '<h1 class="text-subs font-semibold text-base sm:text-lg truncate">foo.bin</h1>',
        "html.parser",
    )

    with (
        patch(
            "src.downloaders.album_downloader.fetch_page",
            return_value=soup,
        ),
        patch(
            "src.downloaders.album_downloader.get_download_info",
            return_value=(None, "foo.bin"),
        ),
    ):
        await downloader.download_album(max_workers=1)

    # The task must be resolved (marked hidden/completed) rather than left
    # hanging — otherwise the overall counter would never reach total.
    hidden = [u for _, u in mgr.task_updates if u["visible"] is False]
    assert hidden, "task must be hidden when link resolution fails"
    assert any("Download link unresolved" in evt for evt, _ in mgr.logs)
