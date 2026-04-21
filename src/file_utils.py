"""Utilities functions for file input and output operations.

It includes methods to read the contents of a file and to write content to a file,
with optional support for clearing the file.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from .config import (
    ALLOWED_DOWNLOAD_ROOT,
    DOWNLOAD_FOLDER,
    MAX_FILENAME_LEN,
    SESSION_LOG,
    VALID_CHARACTERS_REGEX,
)


class PathOutsideSandboxError(ValueError):
    """Raised when a caller-supplied path escapes ``ALLOWED_DOWNLOAD_ROOT``."""


def resolve_within_allowed_root(
    candidate: str,
    *,
    root: str | None = None,
) -> Path:
    """Resolve ``candidate`` and assert it is under :data:`ALLOWED_DOWNLOAD_ROOT`.

    Used by the FastAPI layer to sandbox attacker-controllable inputs like
    ``custom_path`` and ``/api/directories?basePath``. Tilde is expanded,
    then the path is resolved (following symlinks) and checked against the
    allowed root. Raises :class:`PathOutsideSandboxError` on any escape.
    """

    allowed_root = Path(root if root is not None else ALLOWED_DOWNLOAD_ROOT).expanduser().resolve()
    resolved = Path(candidate).expanduser().resolve()
    if resolved != allowed_root and not resolved.is_relative_to(allowed_root):
        raise PathOutsideSandboxError(
            f"{resolved} is outside allowed root {allowed_root}",
        )
    return resolved


def read_file(filename: str) -> list[str]:
    """Read the contents of a file and returns a list of its lines."""
    with Path(filename).open(encoding="utf-8") as file:
        return file.read().splitlines()


def write_file(filename: str, content: str = "") -> None:
    """Write content to a specified file.

    If content is not provided, the file is cleared.
    """
    path = Path(filename)
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        file.write(content)


def write_on_session_log(content: str) -> None:
    """Append content to the session log file."""
    path = Path(SESSION_LOG)
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(f"{content}\n")


def log_maintenance_event(subdomain: str, status: str, url: str) -> None:
    """Log maintenance-related events to the session log with a special format.

    Args:
        subdomain: The subdomain name (e.g., "Cdn13").
        status: The current status (e.g., "Maintenance", "Operational").
        url: The URL that was affected.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[MAINTENANCE] {timestamp} | {subdomain} | {status} | {url}"
    write_on_session_log(log_entry)


def format_directory_name(directory_name: str, directory_id: str | None) -> str | None:
    """Format a directory name by appending its ID in parentheses if the ID is provided.

    If the directory ID is `None`, only the directory name is returned.
    """
    if directory_name is None:
        return directory_id

    return f"{directory_name} ({directory_id})" if directory_id is not None else None


def sanitize_directory_name(directory_name: str) -> str:
    """Sanitize a given directory name by replacing invalid characters with underscores.

    Handles the invalid characters specific to Windows, macOS, and Linux.
    """
    invalid_chars_dict = {
        "nt": r'[\\/:*?"<>|]',  # Windows
        "posix": r"[/:]",       # macOS and Linux
    }
    invalid_chars = invalid_chars_dict.get(os.name)
    return re.sub(invalid_chars, "_", directory_name)


def create_download_directory(
    directory_name: str,
    custom_path: str | None = None,
) -> str:
    """Create a directory for downloads if it doesn't exist."""
    # Sanitizing the directory name (album ID), if provided
    sanitized_directory_name = (
        sanitize_directory_name(directory_name) if directory_name else None
    )

    # Determine the base download path.
    base_path = (
        Path(custom_path) / DOWNLOAD_FOLDER if custom_path else Path(DOWNLOAD_FOLDER)
    )

    # Albums containing a single file will be directly downloaded into the 'Downloads'
    # folder, without creating a subfolder for the album ID.
    download_path = (
        base_path / sanitized_directory_name if sanitized_directory_name else base_path
    )

    # Create the directory if it doesn't exist
    try:
        download_path.mkdir(parents=True, exist_ok=True)

    except OSError as os_err:
        log_message = f"Error creating 'Downloads' directory: {os_err}"
        logging.exception(log_message)
        sys.exit(1)

    return str(download_path)


def remove_invalid_characters(text: str) -> str:
    """Remove invalid characters from the input string.

    This function keeps only letters (both uppercase and lowercase), digits, spaces,
    hyphens ('-'), and underscores ('_').
    """
    return re.sub(VALID_CHARACTERS_REGEX, "", text)


_LEADING_ALNUM_RUN = re.compile(r"^[A-Za-z0-9]+")
_MAX_EXTENSION_LEN = 16  # typical real extensions top out well below this


def _sanitize_extension(extension: str) -> str:
    """Normalise a filename extension to a safe whitelist.

    Keeps only the leading run of alphanumerics after the dot, truncated to
    :data:`_MAX_EXTENSION_LEN`. Stops at the first non-alnum character so
    scraped-URL residue like ``".jpg?width=1024"`` or Windows-hostile
    ``".jp:g"`` collapses to ``".jpg"`` rather than concatenating the
    gibberish tail. Returns an empty string when nothing survives.
    """

    if not extension:
        return ""
    body = extension[1:] if extension.startswith(".") else extension
    match = _LEADING_ALNUM_RUN.match(body)
    if not match:
        return ""
    safe = match.group(0)[:_MAX_EXTENSION_LEN]
    return f".{safe}"


def truncate_filename(filename: str) -> str:
    """Return a sanitised, flattened filename for on-disk storage.

    Strips any directory components from the scraped filename before cleaning
    so an attacker-controlled value like ``"../evil/pwn.jpg"`` collapses to
    ``"pwn.jpg"`` rather than surviving a path traversal through the later
    ``download_path / formatted_filename`` join. The result is always a flat
    filename — no separators, no parent-directory markers — and is
    guaranteed to be ``<= MAX_FILENAME_LEN`` bytes so filesystems that
    impose name-length limits don't error on writes.
    """

    # Take only the terminal component so ``..`` / ``/`` / ``\\`` segments
    # are dropped before anything else touches the value.
    terminal = Path(filename).name
    stem = Path(terminal).stem
    extension = Path(terminal).suffix

    safe_stem = remove_invalid_characters(stem)
    safe_ext = _sanitize_extension(extension)

    # When the sanitised extension alone meets or exceeds the limit, drop
    # it entirely — keeping a truncated middle of the extension would
    # produce nonsense like ``.jpegjpegjp`` and still risk overrun.
    if len(safe_ext) >= MAX_FILENAME_LEN:
        safe_ext = ""

    budget = MAX_FILENAME_LEN - len(safe_ext)
    if len(safe_stem) > budget:
        safe_stem = safe_stem[:budget]

    return f"{safe_stem}{safe_ext}"
