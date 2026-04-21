"""Tests for :mod:`src.file_utils` — filename sanitisation + path sandbox."""

# pylint: disable=missing-function-docstring
from __future__ import annotations

from pathlib import Path

import pytest

from src.file_utils import (
    PathOutsideSandboxError,
    resolve_within_allowed_root,
    truncate_filename,
)


class TestTruncateFilename:
    """Filenames coming from scraped HTML must collapse to safe flat names."""

    def test_strips_directory_components(self) -> None:
        """``../evil/pwn.jpg`` must not traverse — only the terminal segment survives."""

        assert "/" not in truncate_filename("../../etc/pwn.jpg")
        assert "\\" not in truncate_filename("..\\..\\windows\\pwn.jpg")
        assert ".." not in truncate_filename("../../etc/pwn.jpg")

    def test_preserves_terminal_stem_and_extension(self) -> None:
        assert truncate_filename("foo.bar.jpg").endswith(".jpg")
        # Spaces pass through ``remove_invalid_characters`` (regex allows ``\s``);
        # assert the legible stem survives rather than over-asserting on shape.
        result = truncate_filename("foo bar.jpg")
        assert "foo" in result and "bar" in result and result.endswith(".jpg")

    def test_scrubs_invalid_characters(self) -> None:
        result = truncate_filename("rm -rf ~ ; cat $PWD.jpg")
        assert "$" not in result
        assert ";" not in result
        assert result.endswith(".jpg")

    def test_truncates_long_names_respecting_extension(self) -> None:
        long_stem = "a" * 500
        result = truncate_filename(f"{long_stem}.jpg")
        assert result.endswith(".jpg")
        assert len(result) <= 120  # MAX_FILENAME_LEN

    def test_extension_with_query_string_is_sanitised(self) -> None:
        """Regression for PR2 review: ``.jpg?x=1`` must not survive to disk.

        Windows and macOS reject ``?`` in filenames; the old defensive
        check only caught traversal markers, so query-string residue from
        scraped URLs could land in ``final_path`` and crash the write.
        """

        result = truncate_filename("photo.jpg?width=1024")
        assert "?" not in result
        assert "=" not in result
        assert result.endswith(".jpg")

    def test_extension_strips_os_invalid_characters(self) -> None:
        """Colons, asterisks, and pipes are dropped from the extension."""

        result = truncate_filename("foo.jp:g|bar")
        assert ":" not in result
        assert "|" not in result

    def test_result_always_within_max_length(self) -> None:
        """Even a pathological long extension cannot push the name past the cap."""

        # Extension body of 500 chars → after sanitise/cap it stays well inside
        # MAX_FILENAME_LEN rather than overrunning it.
        result = truncate_filename("short." + "x" * 500)
        assert len(result) <= 120

    def test_extension_only_alnum_survives(self) -> None:
        """The whitelist keeps letters/digits in the extension and drops the rest."""

        result = truncate_filename("pic.JPEG2000")
        assert result.endswith(".JPEG2000")


class TestResolveWithinAllowedRoot:
    """The web handlers depend on this to sandbox custom_path / basePath."""

    def test_accepts_path_under_root(self, tmp_path: Path) -> None:
        target = tmp_path / "sub"
        target.mkdir()
        resolved = resolve_within_allowed_root(str(target), root=str(tmp_path))
        assert resolved == target.resolve()

    def test_accepts_root_itself(self, tmp_path: Path) -> None:
        resolved = resolve_within_allowed_root(str(tmp_path), root=str(tmp_path))
        assert resolved == tmp_path.resolve()

    def test_rejects_parent(self, tmp_path: Path) -> None:
        with pytest.raises(PathOutsideSandboxError):
            resolve_within_allowed_root(str(tmp_path.parent), root=str(tmp_path))

    def test_rejects_absolute_escape(self, tmp_path: Path) -> None:
        with pytest.raises(PathOutsideSandboxError):
            resolve_within_allowed_root("/etc", root=str(tmp_path))

    def test_rejects_dot_dot_escape(self, tmp_path: Path) -> None:
        with pytest.raises(PathOutsideSandboxError):
            resolve_within_allowed_root(
                str(tmp_path / "sub" / ".." / ".."),
                root=str(tmp_path),
            )
