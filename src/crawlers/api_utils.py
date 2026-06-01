"""Module that resolves signed media download URLs from Bunkr item pages.

Bunkr retired the old ``POST /api/vs`` + XOR-decrypt scheme (the endpoint now
returns 404). Item pages instead embed the raw CDN URL (``jsCDN``) and a signing
endpoint (``signUrl``) as plaintext inline ``var`` declarations. The CDN itself
is gated behind a short-lived ``token``/``ex`` pair issued by that endpoint, so
resolving a download is now two stateless steps:

1. read ``jsCDN`` + ``signUrl`` out of the page,
2. ``GET {signUrl}?path={encoded CDN path}`` to obtain ``{token, ex}`` and append
   them to the raw CDN URL.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode, urlparse, urlunparse

import requests

from src.config import HEADERS, HTTPStatus, NetworkContext, SIGN_URL_ALLOWED_HOSTS

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

# Inline ``var jsCDN = "..."`` / ``var signUrl = "..."`` declarations. The values
# are captured verbatim (including any JSON ``\/`` slash-escaping) and unescaped
# by ``_unescape``.
CDN_URL_REGEX = re.compile(r'jsCDN\s*=\s*"([^"]+)"')
SIGN_URL_REGEX = re.compile(r'signUrl\s*=\s*"([^"]+)"')


def _unescape(value: str) -> str:
    """Undo the JSON ``\\/`` slash-escaping Bunkr emits in inline script vars."""

    return value.replace("\\/", "/")


def _is_trusted_sign_url(sign_url: str) -> bool:
    """Return whether ``sign_url`` is safe to issue a server-side request to.

    The signing host is read from page content; in the web path the originating
    URL is user-controlled, so a crafted page could point ``signUrl`` at an
    internal host (cloud metadata, localhost) and turn the sign request into an
    SSRF. Require HTTPS and an allowlisted host (see ``SIGN_URL_ALLOWED_HOSTS``).
    """
    parsed = urlparse(sign_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname
    return any(
        host == allowed or host.endswith(f".{allowed}")
        for allowed in SIGN_URL_ALLOWED_HOSTS
    )


def extract_media_sources(soup: BeautifulSoup) -> tuple[str, str] | None:
    """Pull the raw CDN URL and signing endpoint from an item page.

    Returns ``(cdn_url, sign_url)`` with slashes unescaped, or ``None`` when
    either marker is absent (page shape changed, or the item was removed).
    """
    cdn_url: str | None = None
    sign_url: str | None = None

    for script in soup.find_all("script"):
        script_text = script.get_text()
        if cdn_url is None:
            cdn_match = CDN_URL_REGEX.search(script_text)
            if cdn_match:
                cdn_url = _unescape(cdn_match.group(1))
        if sign_url is None:
            sign_match = SIGN_URL_REGEX.search(script_text)
            if sign_match:
                sign_url = _unescape(sign_match.group(1))
        if cdn_url and sign_url:
            break

    if not cdn_url or not sign_url:
        return None
    return cdn_url, sign_url


def _request_sign_token(
    sign_url: str,
    cdn_path: str,
    headers: dict[str, str],
) -> tuple[str, str] | None:
    """Exchange a CDN path for a ``(token, ex)`` pair via the signing endpoint.

    The request mirrors the page's own ``signUrl + '?path=' +
    encodeURIComponent(path)`` call; ``None`` is returned on any network error,
    non-200 response, or malformed payload.
    """
    # ``quote(safe="")`` matches ``encodeURIComponent`` (encodes the path's
    # slashes to ``%2F``), which is what the signing endpoint expects.
    request_url = f"{sign_url}?path={quote(cdn_path, safe='')}"

    try:
        with requests.Session() as session:
            session.headers.update(headers)
            response = session.get(request_url)

        if response.status_code != HTTPStatus.OK:
            logging.warning(
                "Sign endpoint returned %s for path '%s'",
                response.status_code,
                cdn_path,
            )
            return None

        payload = response.json()
        return str(payload["token"]), str(payload["ex"])

    except (requests.RequestException, ValueError, KeyError, TypeError) as err:
        logging.exception("Failed to sign CDN url for '%s': %s", cdn_path, err)
        return None


def get_signed_download_url(
    soup: BeautifulSoup | None,
    *,
    network: NetworkContext | None = None,
) -> str | None:
    """Resolve the time-limited, signed CDN URL for an item page.

    Reads ``jsCDN``/``signUrl`` from ``soup``, exchanges the CDN path for a
    ``token``/``ex`` pair, and returns the CDN URL with those query parameters
    appended. Returns ``None`` (rather than raising) whenever the page lacks the
    expected markers or signing fails, so callers can distinguish "no link" from
    a crash.
    """
    if soup is None:
        return None

    sources = extract_media_sources(soup)
    if sources is None:
        logging.warning("Could not locate jsCDN/signUrl on item page")
        return None

    cdn_url, sign_url = sources
    if not _is_trusted_sign_url(sign_url):
        logging.warning("Refusing untrusted media signing endpoint: %s", sign_url)
        return None

    headers = network.headers if network else HEADERS
    token_pair = _request_sign_token(sign_url, urlparse(cdn_url).path, headers)
    if token_pair is None:
        return None

    token, expiry = token_pair
    parsed = urlparse(cdn_url)
    return urlunparse(parsed._replace(query=urlencode({"token": token, "ex": expiry})))
