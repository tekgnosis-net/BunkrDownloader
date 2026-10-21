"""Transfer knobs: env defaults/clamps, per-job precedence, CLI flags."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

import importlib
from argparse import ArgumentParser, Namespace

import pytest


def _reload_config():
    from src import config  # pylint: disable=import-outside-toplevel
    return importlib.reload(config)


@pytest.mark.parametrize(
    ("env", "attr", "expected"),
    [
        ({}, "DOWNLOAD_SEGMENTS", 4),
        ({"DOWNLOAD_SEGMENTS": "99"}, "DOWNLOAD_SEGMENTS", 16),
        ({"DOWNLOAD_SEGMENTS": "0"}, "DOWNLOAD_SEGMENTS", 1),
        ({"DOWNLOAD_SEGMENTS": "lots"}, "DOWNLOAD_SEGMENTS", 4),
        ({}, "SEGMENT_MIN_FILE_SIZE_MB", 32),
        ({"SEGMENT_MIN_FILE_SIZE_MB": "0"}, "SEGMENT_MIN_FILE_SIZE_MB", 1),
        ({}, "MAX_CONCURRENT_CONNECTIONS", 12),
        ({"MAX_CONCURRENT_CONNECTIONS": "1000"}, "MAX_CONCURRENT_CONNECTIONS", 64),
        ({}, "PARTIAL_MAX_AGE_HOURS", 168),
        ({"PARTIAL_MAX_AGE_HOURS": "0"}, "PARTIAL_MAX_AGE_HOURS", 0),
        ({}, "LINK_REFRESH_MAX", 2),
        ({"LINK_REFRESH_MAX": "99"}, "LINK_REFRESH_MAX", 10),
        ({"LINK_REFRESH_MAX": "-3"}, "LINK_REFRESH_MAX", 0),
        ({"LINK_REFRESH_MAX": "many"}, "LINK_REFRESH_MAX", 2),
        ({}, "MANIFEST_RESET_MAX", 1),
        ({"MANIFEST_RESET_MAX": "99"}, "MANIFEST_RESET_MAX", 5),
        ({"MANIFEST_RESET_MAX": "-1"}, "MANIFEST_RESET_MAX", 0),
        ({"MANIFEST_RESET_MAX": "junk"}, "MANIFEST_RESET_MAX", 1),
    ],
)
def test_transfer_knobs_env_default_and_clamp(monkeypatch, env, attr, expected):
    for name in ("DOWNLOAD_SEGMENTS", "SEGMENT_MIN_FILE_SIZE_MB",
                 "MAX_CONCURRENT_CONNECTIONS", "PARTIAL_MAX_AGE_HOURS",
                 "LINK_REFRESH_MAX", "MANIFEST_RESET_MAX"):
        monkeypatch.delenv(name, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    try:
        assert getattr(_reload_config(), attr) == expected
    finally:
        for key in env:
            monkeypatch.delenv(key, raising=False)
        _reload_config()


def test_resolve_transfer_settings_defaults_when_args_missing():
    from src.config import resolve_transfer_settings  # pylint: disable=import-outside-toplevel
    settings = resolve_transfer_settings(None)
    assert settings.segments == 4
    assert settings.segment_min_bytes == 32 * 1024 * 1024
    assert settings.max_connections == 12
    assert settings.partial_max_age_hours == 168


def test_resolve_transfer_settings_per_job_wins_and_is_clamped():
    from src.config import resolve_transfer_settings  # pylint: disable=import-outside-toplevel
    args = Namespace(
        segments=8, segment_min_size_mb=5000, max_connections=0, partial_max_age_hours=None,
    )
    settings = resolve_transfer_settings(args)
    assert settings.segments == 8
    assert settings.segment_min_bytes == 4096 * 1024 * 1024   # clamped to 4096 MB
    assert settings.max_connections == 1                      # clamped up to 1
    assert settings.partial_max_age_hours == 168              # None -> env/default


def test_per_job_max_connections_may_exceed_env_default():
    from src.config import resolve_transfer_settings  # pylint: disable=import-outside-toplevel
    assert resolve_transfer_settings(Namespace(max_connections=64)).max_connections == 64
    assert resolve_transfer_settings(Namespace(max_connections=4)).max_connections == 4
    assert resolve_transfer_settings(Namespace(max_connections=500)).max_connections == 64


def test_resolve_link_refresh_and_manifest_reset():
    from src.config import resolve_transfer_settings  # pylint: disable=import-outside-toplevel
    base = resolve_transfer_settings(None)
    assert (base.link_refresh_max, base.manifest_reset_max) == (2, 1)
    s = resolve_transfer_settings(Namespace(link_refresh_max=7, manifest_reset_max=3))
    assert (s.link_refresh_max, s.manifest_reset_max) == (7, 3)
    s = resolve_transfer_settings(Namespace(link_refresh_max=99, manifest_reset_max=-4))
    assert (s.link_refresh_max, s.manifest_reset_max) == (10, 0)
    s = resolve_transfer_settings(Namespace(link_refresh_max=None, manifest_reset_max="x"))
    assert (s.link_refresh_max, s.manifest_reset_max) == (2, 1)


def test_cli_flags_registered_with_env_defaults():
    from src.config import add_common_arguments  # pylint: disable=import-outside-toplevel
    parser = ArgumentParser()
    add_common_arguments(parser)
    ns = parser.parse_args([])
    assert ns.segments == 4
    assert ns.segment_min_size_mb == 32
    assert ns.max_connections == 12
    assert ns.partial_max_age_hours == 168
    assert (ns.link_refresh_max, ns.manifest_reset_max) == (2, 1)
    ns = parser.parse_args(["--link-refresh-max", "5", "--manifest-reset-max", "0"])
    assert (ns.link_refresh_max, ns.manifest_reset_max) == (5, 0)
    ns = parser.parse_args(["--segments", "2", "--segment-min-size-mb", "64",
                            "--max-connections", "6", "--partial-max-age-hours", "0"])
    assert (ns.segments, ns.segment_min_size_mb, ns.max_connections,
            ns.partial_max_age_hours) == (2, 64, 6, 0)
