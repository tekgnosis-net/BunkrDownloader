"""Integration tests for PR2 security: path sandbox, auth, CORS."""

# Thin fake doubles + intentionally localised imports for monkeypatch
# sequencing make the usual pylint rules noise here.
# pylint: disable=missing-function-docstring,too-few-public-methods
# pylint: disable=import-outside-toplevel,unused-argument
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.web.app import app as fastapi_app
_ = patch  # referenced inside test bodies; keep the import

# ``src.web.__init__`` does ``from .app import app`` which shadows the
# submodule on the package namespace; ``sys.modules`` keeps the real module
# object so monkeypatching ``API_ACCESS_TOKEN`` works by reference.
_web_app_module = sys.modules["src.web.app"]


class TestPathSandbox:
    """``custom_path`` and ``basePath`` must resolve under ALLOWED_DOWNLOAD_ROOT."""

    def test_custom_path_outside_root_returns_422(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path,
    ) -> None:
        # file_utils reads ALLOWED_DOWNLOAD_ROOT as a module global at call time,
        # so monkeypatch suffices.
        monkeypatch.setattr("src.file_utils.ALLOWED_DOWNLOAD_ROOT", str(tmp_path))

        with TestClient(fastapi_app) as client:
            resp = client.post(
                "/api/downloads",
                json={
                    "urls": ["https://bunkr.test/a/x"],
                    "custom_path": "/etc",
                },
            )
            assert resp.status_code == 422
            assert "outside allowed root" in resp.json()["detail"]

    def test_directories_outside_root_returns_422(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path,
    ) -> None:
        monkeypatch.setattr("src.file_utils.ALLOWED_DOWNLOAD_ROOT", str(tmp_path))

        with TestClient(fastapi_app) as client:
            resp = client.get("/api/directories", params={"basePath": "/etc"})
            assert resp.status_code == 422

    def test_directories_under_root_succeeds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path,
    ) -> None:
        (tmp_path / "nested").mkdir()
        monkeypatch.setattr("src.file_utils.ALLOWED_DOWNLOAD_ROOT", str(tmp_path))

        with TestClient(fastapi_app) as client:
            resp = client.get("/api/directories", params={"basePath": str(tmp_path)})
            assert resp.status_code == 200, resp.text
            assert any("nested" in d for d in resp.json()["directories"])

    def test_directories_default_path_materialises_missing_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path,
    ) -> None:
        """Fresh install: sandbox root doesn't exist yet.

        Before, the UI mounted, hit /api/directories with no basePath, got
        404 from the non-existent root, and rendered a scary "Failed to
        load directories" toast. The endpoint now auto-creates the root on
        the default path so the picker returns an empty listing instead.
        """

        missing_root = tmp_path / "Downloads"
        assert not missing_root.exists()
        monkeypatch.setattr("src.file_utils.ALLOWED_DOWNLOAD_ROOT", str(missing_root))
        monkeypatch.setattr("src.web.app.ALLOWED_DOWNLOAD_ROOT", str(missing_root))

        with TestClient(fastapi_app) as client:
            resp = client.get("/api/directories")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["directories"] == []
            assert missing_root.exists() and missing_root.is_dir()

    def test_directories_user_supplied_missing_path_still_404(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path,
    ) -> None:
        """Explicit basePath that doesn't exist must not be auto-created.

        Auto-create is only for the default (sandbox-root) path. If the
        user types a non-existent sub-path, they should see 404 so typos
        and stale paths surface honestly rather than silently materialising.
        """

        sandbox_root = tmp_path / "Downloads"
        sandbox_root.mkdir()
        monkeypatch.setattr("src.file_utils.ALLOWED_DOWNLOAD_ROOT", str(sandbox_root))
        monkeypatch.setattr("src.web.app.ALLOWED_DOWNLOAD_ROOT", str(sandbox_root))

        missing_subpath = sandbox_root / "nope"
        with TestClient(fastapi_app) as client:
            resp = client.get("/api/directories", params={"basePath": str(missing_subpath)})
            assert resp.status_code == 404
            assert not missing_subpath.exists()

    def test_custom_path_parent_of_root_accepted_when_effective_is_inside(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """Regression for PR2 review: validate the EFFECTIVE path, not the raw value.

        ``create_download_directory`` appends ``DOWNLOAD_FOLDER`` to
        ``custom_path``, so the legitimate ``custom_path=<root parent>``
        (which yields ``<root>/Downloads`` after the join) must be
        accepted. Checking only the raw ``custom_path`` previously
        rejected this as "outside allowed root".
        """

        # Sandbox root is ``tmp_path / "Downloads"``; passing ``tmp_path``
        # as custom_path should be fine because the effective download
        # directory is ``tmp_path / "Downloads"`` — equal to the root.
        download_root = tmp_path / "Downloads"
        download_root.mkdir()
        monkeypatch.setattr(
            "src.file_utils.ALLOWED_DOWNLOAD_ROOT", str(download_root),
        )
        monkeypatch.setattr(
            "src.web.app.ALLOWED_DOWNLOAD_ROOT", str(download_root),
        )

        async def _noop(bunkr_status, url, manager, args=None):  # noqa: ARG001
            pass

        with (
            patch("src.web.app.validate_and_download", side_effect=_noop),
            patch("src.web.app.get_bunkr_status_cached", return_value={}),
            TestClient(fastapi_app) as client,
        ):
            resp = client.post(
                "/api/downloads",
                json={
                    "urls": ["https://bunkr.test/a/x"],
                    "custom_path": str(tmp_path),
                },
            )
            # ``tmp_path`` alone is a parent of the sandbox root, but after
            # the ``/Downloads`` join it equals the root — must be accepted.
            assert resp.status_code == 200, resp.text


class TestBearerAuth:
    """``require_auth`` reads ``API_ACCESS_TOKEN`` at call time via module lookup."""

    def test_unauthenticated_by_default(self) -> None:
        """Clean import leaves API_ACCESS_TOKEN=None → routes are accessible."""

        with TestClient(fastapi_app) as client:
            resp = client.get("/api/meta")
            assert resp.status_code == 200

    def test_missing_token_returns_401_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(_web_app_module, "API_ACCESS_TOKEN", "s3cret")

        with TestClient(fastapi_app) as client:
            resp = client.get("/api/meta")
            assert resp.status_code == 401
            assert "bearer" in resp.json()["detail"].lower()

    def test_valid_token_accepted(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(_web_app_module, "API_ACCESS_TOKEN", "s3cret")

        with TestClient(fastapi_app) as client:
            resp = client.get("/api/meta", headers={"Authorization": "Bearer s3cret"})
            assert resp.status_code == 200

    def test_wrong_token_returns_401(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(_web_app_module, "API_ACCESS_TOKEN", "s3cret")

        with TestClient(fastapi_app) as client:
            resp = client.get(
                "/api/meta", headers={"Authorization": "Bearer wrong"},
            )
            assert resp.status_code == 401
            assert "invalid" in resp.json()["detail"].lower()

    def test_authorize_websocket_rejects_missing_token(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Browsers can't set Authorization on ``new WebSocket()`` — ``?token=`` is the channel.

        Tested against the helper directly because the TestClient WebSocket
        session is sensitive to the pre-accept-close ordering; the helper
        captures the same logic without the client/server dance.
        """

        monkeypatch.setattr(_web_app_module, "API_ACCESS_TOKEN", "s3cret")
        from src.web.app import _authorize_websocket  # import after monkeypatch

        class _FakeWS:
            def __init__(self, params: dict[str, str]) -> None:
                self.query_params = params

        assert _authorize_websocket(_FakeWS({})) is False
        assert _authorize_websocket(_FakeWS({"token": "wrong"})) is False
        assert _authorize_websocket(_FakeWS({"token": "s3cret"})) is True

    def test_authorize_websocket_permits_when_token_unset(self) -> None:
        """With no API_ACCESS_TOKEN configured, WebSocket auth is a no-op."""

        from src.web.app import _authorize_websocket

        class _FakeWS:
            query_params = {}

        # The default token is None, so the helper accepts any connection.
        assert _authorize_websocket(_FakeWS()) is True


class TestCorsDefaults:
    """CORS must reject wildcard origins but allow the localhost regex default."""

    def test_evil_origin_receives_no_allow_origin_header(self) -> None:
        with TestClient(fastapi_app) as client:
            resp = client.options(
                "/api/meta",
                headers={
                    "Origin": "https://evil.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            # No Access-Control-Allow-Origin header means the preflight is
            # effectively denied for that origin.
            lowered = {k.lower() for k in resp.headers.keys()}
            assert "access-control-allow-origin" not in lowered

    def test_localhost_origin_allowed(self) -> None:
        with TestClient(fastapi_app) as client:
            resp = client.options(
                "/api/meta",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
