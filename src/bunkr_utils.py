"""Utilities to fetch the operational status of servers from the Bunkr status page."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .config import HEADERS, STATUS_PAGE

# Module-level cache for status page results: {cache_key: (fetch_time, status_dict)}
_status_cache: dict[str, tuple[datetime, dict[str, str]]] = {}


def fetch_page(url: str) -> BeautifulSoup | None:
    """Fetch the HTML content of a page at the given URL."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()

    except requests.RequestException:
        logging.exception("An error occurred while fetching the status page.")
        return None

    return BeautifulSoup(response.text, "html.parser")


def get_bunkr_status() -> dict[str, str]:
    """Fetch the status of servers from the status page and return a dictionary."""
    soup = fetch_page(STATUS_PAGE)
    if soup is None:
        logging.warning("Unable to fetch Bunkr status page; continuing without host data")
        return {}

    bunkr_status: dict[str, str] = {}

    try:
        server_items = soup.find_all(
            "div",
            {
                "class": (
                    "flex items-center gap-4 py-4 border-b border-soft last:border-b-0"
                ),
            },
        )

        for server_item in server_items:
            server_name = server_item.find("p").get_text(strip=True)
            server_status = server_item.find("span").get_text(strip=True)
            bunkr_status[server_name] = server_status

    except AttributeError as attr_err:
        logging.exception("Error extracting server data: %s", attr_err)
        return {}

    return bunkr_status


def get_offline_servers(bunkr_status: dict[str, str] | None = None) -> dict[str, str]:
    """Return a dictionary of servers that are not operational."""
    bunkr_status = bunkr_status or get_bunkr_status()
    return {
        server_name: server_status
        for server_name, server_status in bunkr_status.items()
        if server_status != "Operational"
    }


def get_subdomain(download_link: str) -> str:
    """Extract the capitalized subdomain from a given URL."""
    netloc = urlparse(download_link).netloc
    return netloc.split(".")[0].capitalize()


def subdomain_is_offline(
    download_link: str, bunkr_status: dict[str, str] | None = None,
) -> bool:
    """Check if the subdomain from the given download link is marked as offline."""
    offline_servers = get_offline_servers(bunkr_status)
    subdomain = get_subdomain(download_link)
    return subdomain in offline_servers


def mark_subdomain_as_offline(bunkr_status: dict[str, str], download_link: str) -> str:
    """Mark the subdomain of a given download link as offline in the Bunkr status."""
    subdomain = get_subdomain(download_link)
    bunkr_status[subdomain] = "Non-operational"
    return subdomain


def refresh_server_status(
    subdomain: str,
    bunkr_status: dict[str, str],
    cache_ttl_seconds: int = 60,
) -> tuple[str, bool]:
    """Refresh the status of a specific subdomain from the status page.

    Args:
        subdomain: The subdomain name to check (e.g., "Cdn13").
        bunkr_status: The current status dictionary to update in-place.
        cache_ttl_seconds: Time-to-live for cached status in seconds.

    Returns:
        A tuple of (current_status, was_updated) where:
        - current_status: The latest status string for the subdomain.
        - was_updated: True if the status was refreshed from the server.
    """
    cache_key = "bunkr_status"
    now = datetime.now()

    # Check cache first
    if cache_key in _status_cache:
        fetch_time, cached_status = _status_cache[cache_key]
        if now - fetch_time < timedelta(seconds=cache_ttl_seconds):
            # Cache is still valid
            current_status = cached_status.get(subdomain, "Unknown")
            if subdomain in cached_status:
                bunkr_status[subdomain] = cached_status[subdomain]
            return current_status, False

    # Cache expired or not present, fetch fresh status
    fresh_status = get_bunkr_status()
    if fresh_status:
        _status_cache[cache_key] = (now, fresh_status)
        # Update the provided dictionary with all fresh data
        bunkr_status.update(fresh_status)
        current_status = fresh_status.get(subdomain, "Unknown")
        return current_status, True

    # Fallback: couldn't fetch fresh status
    return bunkr_status.get(subdomain, "Unknown"), False
