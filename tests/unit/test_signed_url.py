"""Tests for the signed-CDN-URL resolution that replaced the ``/api/vs`` scheme.

Bunkr retired the ``POST /api/vs`` + XOR-decrypt flow (the endpoint now 404s).
Item pages instead embed the raw CDN URL (``jsCDN``) and a signing endpoint
(``signUrl``) as plaintext inline ``var`` declarations; the CDN is gated behind
a short-lived ``token``/``ex`` pair issued by that endpoint. These tests pin the
new resolver to that contract.
"""

# Thin HTTP doubles; bs4 imported at module scope is fine for these unit tests.
# pylint: disable=missing-function-docstring,too-few-public-methods
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from src.crawlers.api_utils import extract_media_sources, get_signed_download_url
from src.crawlers.crawler_utils import get_item_download_link

# Mirrors a real item page: ``jsCDN`` uses JSON ``\/`` slash-escaping, ``signUrl``
# does not, and a second ``const slug`` script (live-viewer websocket) is present
# as a decoy that must NOT be mistaken for the download source.
ITEM_PAGE_HTML = """
<html><body>
<script type="text/javascript">
    var videoCoverUrl = "https:\\/\\/static.scdn.st\\/x\\/thumbs\\/foo.mp4_grid.png";
    var jsCDN         = "https:\\/\\/c4ta-b.cdn.cr\\/storage\\/media\\/foo.mp4";
    var jsType        = "video\\/mp4";
    var jsSlug        = "foo.mp4";
    var signUrl       = "https://glb-apisign.cdn.cr/sign";
</script>
<script>
    const slug = "foo.mp4";
    const ws = new WebSocket("wss://host/ws/viewers?file=" + slug);
</script>
</body></html>
"""


def _fake_session(response: MagicMock) -> MagicMock:
    """Build a MagicMock that behaves like ``requests.Session()`` as a context manager."""

    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.get.return_value = response
    return session


def _ok_sign_response(token: str, expiry: int) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"token": token, "ex": expiry}
    return response


def test_extract_media_sources_returns_unescaped_cdn_and_sign_url() -> None:
    soup = BeautifulSoup(ITEM_PAGE_HTML, "html.parser")

    cdn_url, sign_url = extract_media_sources(soup)

    assert cdn_url == "https://c4ta-b.cdn.cr/storage/media/foo.mp4"
    assert sign_url == "https://glb-apisign.cdn.cr/sign"


def test_extract_media_sources_returns_none_when_markers_absent() -> None:
    soup = BeautifulSoup("<html><body><p>removed</p></body></html>", "html.parser")

    assert extract_media_sources(soup) is None


def test_get_signed_download_url_appends_token_and_ex() -> None:
    soup = BeautifulSoup(ITEM_PAGE_HTML, "html.parser")
    session = _fake_session(_ok_sign_response("abc123", 1780293869))

    with patch("src.crawlers.api_utils.requests.Session", return_value=session):
        signed = get_signed_download_url(soup)

    assert signed is not None
    assert signed.startswith("https://c4ta-b.cdn.cr/storage/media/foo.mp4?")
    assert "token=abc123" in signed
    assert "ex=1780293869" in signed

    # The sign endpoint must be queried with the URL-encoded CDN *path*, exactly
    # as the browser's ``signUrl + '?path=' + encodeURIComponent(path)`` does.
    queried_url = session.get.call_args[0][0]
    assert queried_url == (
        "https://glb-apisign.cdn.cr/sign?path=%2Fstorage%2Fmedia%2Ffoo.mp4"
    )


def test_get_signed_download_url_returns_none_on_sign_failure() -> None:
    soup = BeautifulSoup(ITEM_PAGE_HTML, "html.parser")
    failed = MagicMock()
    failed.status_code = 404
    session = _fake_session(failed)

    with patch("src.crawlers.api_utils.requests.Session", return_value=session):
        assert get_signed_download_url(soup) is None


def test_get_signed_download_url_returns_none_when_sources_missing() -> None:
    soup = BeautifulSoup("<html><body><p>removed</p></body></html>", "html.parser")

    # No sources -> never touches the network, returns None.
    assert get_signed_download_url(soup) is None


def test_get_signed_download_url_rejects_untrusted_sign_host() -> None:
    # A malicious/MITM'd page could point ``signUrl`` at an internal host to turn
    # the server-side sign request into an SSRF. The host must be allowlisted, and
    # an untrusted host must short-circuit BEFORE any network call is made.
    html = ITEM_PAGE_HTML.replace(
        "https://glb-apisign.cdn.cr/sign",
        "http://169.254.169.254/sign",
    )
    soup = BeautifulSoup(html, "html.parser")
    session = _fake_session(_ok_sign_response("leaked", 1))

    with patch("src.crawlers.api_utils.requests.Session", return_value=session):
        assert get_signed_download_url(soup) is None

    session.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_item_download_link_resolves_signed_url() -> None:
    soup = BeautifulSoup(ITEM_PAGE_HTML, "html.parser")
    expected = "https://c4ta-b.cdn.cr/storage/media/foo.mp4?token=t&ex=1"

    with patch(
        "src.crawlers.crawler_utils.get_signed_download_url",
        return_value=expected,
    ):
        link = await get_item_download_link("https://bunkr.cr/f/foo.mp4", soup=soup)

    assert link == expected
