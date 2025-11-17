"""Utility modules and functions to support the main application.

These utilities include functions for downloading, file management, URL handling,
progress tracking, and more.

Modules:
    - bunkr_utils: Functions for checking Bunkr status and URL validation.
    - config: Constants and settings used across the project.
    - file_utils: Utilities for managing file operations.
    - general_utils: Miscellaneous utility functions.
    - url_utils: Utilities to analyze and extract details from URLs.

This package is designed to be reusable and modular, allowing its components
to be easily imported and used across different parts of the application.
"""

# src/__init__.py

from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path

try:  # Python >=3.11 ships tomllib
    import tomllib as TOMLIB
except ModuleNotFoundError:  # pragma: no cover - safeguard for older interpreters
    TOMLIB = None
__all__ = [
    "bunkr_utils",
    "config",
    "file_utils",
    "general_utils",
    "url_utils",
    "__version__",
]

_DEFAULT_VERSION = "0.0.0"


def _derive_version() -> str:
    """Resolve the best available application version string."""

    env_version = os.getenv("APP_VERSION")
    if env_version and env_version.lower() != "latest":
        return env_version

    try:
        return metadata.version("bunkrdownloader")
    except metadata.PackageNotFoundError:
        pass

    if TOMLIB is not None:
        pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
        try:
            loaded = TOMLIB.loads(pyproject_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            loaded = None
        if loaded:
            project = loaded.get("project") or {}
            version = project.get("version")
            if isinstance(version, str) and version:
                return version

    return _DEFAULT_VERSION


__version__ = _derive_version()
