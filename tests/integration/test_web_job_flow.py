"""FastAPI integration tests for job event envelopes and cross-job isolation."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.web import app as web_app
from src.web.app import app as fastapi_app


# Signature mirrors validate_and_download so the keyword-only call site
# from _run_download_job keeps working.
async def _fake_validate(bunkr_status, url, manager, args=None, transfer_context=None):  # pylint: disable=unused-argument,line-too-long
    manager.add_overall_task("fake-album", num_tasks=1)
    task = manager.add_task(current_task=0)
    for pct in (25, 50, 75, 100):
        manager.update_task(task, completed=pct)
    manager.update_log(event="info", details=f"done {url}")


def _drain(client: TestClient, job_id: str, min_events: int = 4, timeout: float = 2.0) -> list:
    """Poll /events until we've accumulated at least ``min_events``."""

    deadline = time.time() + timeout
    last: list[dict] = []
    while time.time() < deadline:
        resp = client.get(f"/api/downloads/{job_id}/events")
        payload = resp.json()
        last = payload["events"]
        if len(last) >= min_events:
            return payload["events"]
        time.sleep(0.05)
    return last


def test_event_envelope_shape_and_cursor_alias() -> None:
    """Envelope includes ``event_id``/``ts``; ``next_id`` and ``next_index`` agree."""

    with (
        patch("src.web.app.validate_and_download", side_effect=_fake_validate),
        patch("src.web.app.get_bunkr_status_cached", return_value={}),
        TestClient(fastapi_app) as client,
    ):
        resp = client.post(
            "/api/downloads",
            json={"urls": ["https://bunkr.test/a/abc"]},
        )
        job_id = resp.json()["job_id"]

        events = _drain(client, job_id, min_events=4)
        assert events, "no events buffered"

        payload = client.get(f"/api/downloads/{job_id}/events").json()
        ids = [e["event_id"] for e in payload["events"]]
        assert ids == sorted(ids), "event_id must be monotonic"
        assert all("ts" in e for e in payload["events"])
        assert payload["next_id"] == max(ids)
        assert payload["next_index"] == payload["next_id"], "legacy alias"


def test_ws_hello_frame_precedes_replay() -> None:
    """The WebSocket stream's first frame is always the ``hello`` envelope."""

    with (
        patch("src.web.app.validate_and_download", side_effect=_fake_validate),
        patch("src.web.app.get_bunkr_status_cached", return_value={}),
        TestClient(fastapi_app) as client,
    ):
        job_id = client.post(
            "/api/downloads",
            json={"urls": ["https://bunkr.test/a/x"]},
        ).json()["job_id"]
        time.sleep(0.2)
        with client.websocket_connect(f"/ws/jobs/{job_id}") as ws:
            first = ws.receive_json()
            assert first["type"] == "hello"
            assert "next_id" in first
            assert "ts" in first


def test_parallel_jobs_do_not_cross_contaminate_events() -> None:
    """Two concurrent jobs keep their event streams isolated by job_id."""

    with (
        patch("src.web.app.validate_and_download", side_effect=_fake_validate),
        patch("src.web.app.get_bunkr_status_cached", return_value={}),
        TestClient(fastapi_app) as client,
    ):
        job_a = client.post(
            "/api/downloads",
            json={"urls": ["https://bunkr.test/a/1"]},
        ).json()["job_id"]
        job_b = client.post(
            "/api/downloads",
            json={"urls": ["https://bunkr.test/a/2"]},
        ).json()["job_id"]

        time.sleep(0.3)
        events_a = client.get(f"/api/downloads/{job_a}/events").json()["events"]
        events_b = client.get(f"/api/downloads/{job_b}/events").json()["events"]

        # Both jobs get their own numbering starting at 1.
        assert events_a[0]["event_id"] == 1
        assert events_b[0]["event_id"] == 1

        # No event text from one job should appear in the other's stream.
        details_a = {e.get("details") for e in events_a}
        details_b = {e.get("details") for e in events_b}
        assert "done https://bunkr.test/a/2" not in details_a
        assert "done https://bunkr.test/a/1" not in details_b


def test_cancel_endpoint_sets_the_jobs_transfer_cancel_event() -> None:
    """``POST /cancel`` must reach download threads, not only the asyncio task."""

    seen: list = []

    async def _blocking(bunkr_status, url, manager, args=None, transfer_context=None):  # pylint: disable=unused-argument
        seen.append(transfer_context)
        await asyncio.sleep(30)

    with (
        patch("src.web.app.validate_and_download", side_effect=_blocking),
        patch("src.web.app.get_bunkr_status_cached", return_value={}),
        TestClient(fastapi_app) as client,
    ):
        job_id = client.post(
            "/api/downloads", json={"urls": ["https://bunkr.test/a/c"]},
        ).json()["job_id"]
        deadline = time.time() + 5
        while not seen and time.time() < deadline:
            time.sleep(0.02)
        assert seen and seen[0] is not None
        assert not seen[0].cancel_event.is_set()

        resp = client.post(f"/api/downloads/{job_id}/cancel")
        assert resp.json()["status"] == "cancelled"
        assert seen[0].cancel_event.is_set()
        assert seen[0].cancel_event is web_app.job_store.get(job_id).cancel_event
