"""Regression tests for NetworkContext isolation and build resolution order."""

from __future__ import annotations

from argparse import Namespace

import pytest

from src import config
from src.config import NetworkContext, build_network_context


def test_build_defaults_to_module_globals() -> None:
    """Without args or overrides the factory mirrors module-level defaults."""

    ctx = build_network_context()

    assert ctx.status_page == config.STATUS_PAGE
    assert ctx.bunkr_api == config.BUNKR_API
    assert ctx.fallback_domain == config.FALLBACK_DOMAIN


def test_build_respects_args_overrides() -> None:
    """Values on the CLI ``Namespace`` take precedence over module defaults."""

    args = Namespace(
        status_page="https://override.status/",
        bunkr_api="https://override.api/api/vs",
        fallback_domain="override.domain",
        user_agent="override-agent/1.0",
        download_referer="https://override.referer/",
    )
    ctx = build_network_context(args)

    assert ctx.status_page == "https://override.status/"
    assert ctx.bunkr_api == "https://override.api/api/vs"
    assert ctx.fallback_domain == "override.domain"
    assert ctx.user_agent == "override-agent/1.0"


def test_explicit_overrides_beat_args() -> None:
    """The resolution order is overrides > args > module defaults."""

    args = Namespace(status_page="https://from-args/", user_agent="from-args")
    ctx = build_network_context(args, overrides={"status_page": "https://from-kw/"})

    assert ctx.status_page == "https://from-kw/"
    assert ctx.user_agent == "from-args"


def test_network_context_is_immutable() -> None:
    """``frozen=True`` prevents accidental mid-flight mutation by callers."""

    ctx = NetworkContext(
        status_page="s", bunkr_api="a", fallback_domain="d",
        user_agent="u", download_referer="r",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        ctx.status_page = "x"  # type: ignore[misc]


def test_building_contexts_does_not_mutate_globals() -> None:
    """Building two contexts for different jobs leaves the process defaults alone."""

    baseline = {
        "status_page": config.STATUS_PAGE,
        "bunkr_api": config.BUNKR_API,
        "fallback_domain": config.FALLBACK_DOMAIN,
        "user_agent": config.HEADERS.get("User-Agent"),
        "download_referer": config.DOWNLOAD_HEADERS.get("Referer"),
    }

    build_network_context(overrides={
        "status_page": "https://a/",
        "bunkr_api": "https://a/api",
        "fallback_domain": "a.cr",
        "user_agent": "a-agent",
        "download_referer": "https://a/ref",
    })
    build_network_context(overrides={
        "status_page": "https://b/",
        "bunkr_api": "https://b/api",
        "fallback_domain": "b.cr",
        "user_agent": "b-agent",
        "download_referer": "https://b/ref",
    })

    assert config.STATUS_PAGE == baseline["status_page"]
    assert config.BUNKR_API == baseline["bunkr_api"]
    assert config.FALLBACK_DOMAIN == baseline["fallback_domain"]
    assert config.HEADERS.get("User-Agent") == baseline["user_agent"]
    assert config.DOWNLOAD_HEADERS.get("Referer") == baseline["download_referer"]
