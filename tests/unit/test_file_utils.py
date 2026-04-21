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
