"""Per-URL outcome reporting for multi-URL batch jobs.

A batch of URLs is the normal way the dashboard is driven, so a single bad
link must not discard the work queued behind it. These tests pin the two
guarantees the UI's succeeded/failed lists rely on: every URL produces
exactly one ``url_result`` envelope, and the job only reports ``failed``
when nothing at all succeeded.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.web.app import app as fastapi_app

TERMINAL = {"completed", "failed", "cancelled"}


def _failing_on(*bad_urls: str):
    """Build a ``validate_and_download`` double that raises for ``bad_urls``."""

    async def _fake(bunkr_status, url, manager, args=None):  # pylint: disable=unused-argument
        if url in bad_urls:
            raise RuntimeError(f"boom {url}")
        manager.update_log(event="info", details=f"done {url}")

    return _fake


def _drain_until_terminal(
    client: TestClient,
    job_id: str,
    timeout: float = 5.0,
) -> list[dict]:
    """Poll ``/events`` until a terminal status envelope lands."""

    deadline = time.time() + timeout
    events: list[dict] = []
    while time.time() < deadline:
        events = client.get(f"/api/downloads/{job_id}/events").json()["events"]
        if any(e.get("type") == "status" and e.get("status") in TERMINAL for e in events):
            return events
        time.sleep(0.05)
    return events


def _url_results(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "url_result"]


def _terminal_status(events: list[dict]) -> str | None:
    for event in reversed(events):
        if event.get("type") == "status" and event.get("status") in TERMINAL:
            return event["status"]
    return None


def test_failed_url_does_not_abort_the_batch() -> None:
    """A URL that raises is recorded and the remaining URLs still run."""

    urls = [
        "https://bunkr.test/a/first",
        "https://bunkr.test/a/broken",
        "https://bunkr.test/a/third",
    ]
    with (
        patch(
            "src.web.app.validate_and_download",
            side_effect=_failing_on("https://bunkr.test/a/broken"),
        ),
        patch("src.web.app.get_bunkr_status_cached", return_value={}),
        TestClient(fastapi_app) as client,
    ):
        job_id = client.post("/api/downloads", json={"urls": urls}).json()["job_id"]
        events = _drain_until_terminal(client, job_id)

        results = _url_results(events)
        assert [r["url"] for r in results] == urls, "every URL must report an outcome"
        assert [r["status"] for r in results] == ["succeeded", "failed", "succeeded"]
        assert results[1]["error"] and "boom" in results[1]["error"]
        assert results[0]["error"] is None

        # One survivor is enough for the job itself to be a success.
        assert _terminal_status(events) == "completed"


def test_url_result_carries_batch_position() -> None:
    """``index``/``total`` let the client match a result to the line it sent."""

    urls = ["https://bunkr.test/a/one", "https://bunkr.test/a/two"]
    with (
        patch("src.web.app.validate_and_download", side_effect=_failing_on()),
        patch("src.web.app.get_bunkr_status_cached", return_value={}),
        TestClient(fastapi_app) as client,
    ):
        job_id = client.post("/api/downloads", json={"urls": urls}).json()["job_id"]
        results = _url_results(_drain_until_terminal(client, job_id))

        assert [r["index"] for r in results] == [1, 2]
        assert {r["total"] for r in results} == {2}


def test_job_fails_only_when_every_url_fails() -> None:
    """With no survivors the job is a genuine failure and says why."""

    urls = ["https://bunkr.test/a/x", "https://bunkr.test/a/y"]
    with (
        patch("src.web.app.validate_and_download", side_effect=_failing_on(*urls)),
        patch("src.web.app.get_bunkr_status_cached", return_value={}),
        TestClient(fastapi_app) as client,
    ):
        job_id = client.post("/api/downloads", json={"urls": urls}).json()["job_id"]
        events = _drain_until_terminal(client, job_id)

        assert [r["status"] for r in _url_results(events)] == ["failed", "failed"]
        assert _terminal_status(events) == "failed"
        assert client.get(f"/api/downloads/{job_id}").json()["error"]


def test_cancel_leaves_unreached_urls_without_a_verdict() -> None:
    """Cancelling reports only what finished, so the rest stay restartable.

    The client keeps every URL that has no ``url_result`` in its input box,
    so emitting a verdict for a URL the job never reached (or abandoned
    mid-flight) would silently drop work the operator still wants.
    """

    started: list[str] = []

    async def _slow(bunkr_status, url, manager, args=None):  # pylint: disable=unused-argument
        started.append(url)
        await asyncio.sleep(5)

    urls = [f"https://bunkr.test/a/{name}" for name in ("one", "two", "three")]
    with (
        patch("src.web.app.validate_and_download", side_effect=_slow),
        patch("src.web.app.get_bunkr_status_cached", return_value={}),
        TestClient(fastapi_app) as client,
    ):
        job_id = client.post("/api/downloads", json={"urls": urls}).json()["job_id"]
        # Let the first URL get under way, then pull the plug.
        deadline = time.time() + 2.0
        while not started and time.time() < deadline:
            time.sleep(0.02)
        assert started, "job never started the first URL"
        client.post(f"/api/downloads/{job_id}/cancel")

        events = _drain_until_terminal(client, job_id)
        assert _terminal_status(events) == "cancelled"
        # Nothing completed, so nothing may claim a verdict — all three URLs
        # remain the client's to retry.
        assert not _url_results(events)


def test_setup_failure_still_fails_the_job_without_url_results() -> None:
    """A pre-loop crash (status fetch) fails the job before any URL is tried."""

    with (
        patch("src.web.app.validate_and_download", side_effect=_failing_on()),
        patch("src.web.app.get_bunkr_status_cached", side_effect=RuntimeError("status down")),
        TestClient(fastapi_app) as client,
    ):
        job_id = client.post(
            "/api/downloads",
            json={"urls": ["https://bunkr.test/a/z"]},
        ).json()["job_id"]
        events = _drain_until_terminal(client, job_id)

        assert not _url_results(events)
        assert _terminal_status(events) == "failed"
