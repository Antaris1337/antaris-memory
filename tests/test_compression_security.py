"""
Security tests for compression.py path traversal fixes.

Covers:
- NI1: str.startswith() bypass is closed (relative_to() is path-aware)
- NW4: workspace=None raises ValueError; workspace=False is explicit opt-out
"""

import os
import sys
import tempfile

import pytest

from antaris_memory.compression import CompressionEngine


# ---------------------------------------------------------------------------
# NI1 — The startswith bypass must be CLOSED
# ---------------------------------------------------------------------------

class TestPathTraversalClosed:
    """The critical str.startswith() bypass must NOT allow escapes."""

    def test_adjacent_directory_is_blocked(self, tmp_path):
        """
        Core regression for NI1.

        workspace = /tmp/xxx/memory
        file      = /tmp/xxx/memory_backup/evil.md

        str("/tmp/xxx/memory_backup/evil.md").startswith("/tmp/xxx/memory") → True
          → OLD code PASSED this — path traversal bypass.

        resolved.relative_to(workspace_resolved) → ValueError
          → NEW code must BLOCK this and return an error dict.
        """
        workspace = tmp_path / "memory"
        adjacent = tmp_path / "memory_backup"
        workspace.mkdir()
        adjacent.mkdir()

        evil_file = adjacent / "evil.md"
        evil_file.write_text("secrets")

        result = CompressionEngine.compress_file(str(evil_file), workspace=str(workspace))
        assert "error" in result
        assert "Path traversal denied" in result["error"]

    def test_dotdot_traversal_blocked(self, tmp_path):
        """../../etc/passwd style traversal must be blocked."""
        workspace = tmp_path / "memory"
        workspace.mkdir()

        traversal = str(workspace / ".." / ".." / "etc" / "passwd")
        result = CompressionEngine.compress_file(traversal, workspace=str(workspace))
        assert "error" in result
        assert "Path traversal denied" in result["error"]

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Symlink creation requires Developer Mode or admin on Windows; "
               "run this test in an elevated shell or with dev-mode enabled.",
    )
    def test_symlink_traversal_blocked(self, tmp_path):
        """Symlink pointing outside the workspace must be blocked.

        Path.resolve() follows symlinks before relative_to() is called,
        so the resolved target path is checked — not the link itself.
        """
        workspace = tmp_path / "memory"
        workspace.mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("outside content")
        link = workspace / "link.md"
        link.symlink_to(outside)

        result = CompressionEngine.compress_file(str(link), workspace=str(workspace))
        # Symlink resolves to /tmp/xxx/outside.md which is NOT inside /tmp/xxx/memory/
        assert "error" in result
        assert "Path traversal denied" in result["error"]

    def test_valid_file_inside_workspace_passes(self, tmp_path):
        """A file genuinely inside the workspace must succeed."""
        workspace = tmp_path / "memory"
        workspace.mkdir()
        valid_file = workspace / "2026-01-01.md"
        valid_file.write_text("## Notes\n- Important point long enough\n")

        result = CompressionEngine.compress_file(str(valid_file), workspace=str(workspace))
        assert "error" not in result
        assert result["original_lines"] == 2

    def test_nested_subdirectory_passes(self, tmp_path):
        """A file in a subdirectory of the workspace must succeed."""
        workspace = tmp_path / "memory"
        sub = workspace / "sub"
        sub.mkdir(parents=True)
        nested = sub / "2026-01-02.md"
        nested.write_text("## Deep\n- a reasonably long item here\n")

        result = CompressionEngine.compress_file(str(nested), workspace=str(workspace))
        assert "error" not in result


# ---------------------------------------------------------------------------
# NW4 — workspace=None must raise ValueError (hard error, not a warning)
# ---------------------------------------------------------------------------

class TestWorkspaceNoneIsHardError:
    def test_no_workspace_raises_value_error(self, tmp_path):
        """compress_file() without workspace must raise ValueError, not warn."""
        f = tmp_path / "test.md"
        f.write_text("## Test\n- a point long enough to matter\n")

        with pytest.raises(ValueError, match="workspace"):
            CompressionEngine.compress_file(str(f))

    def test_workspace_none_explicit_raises(self, tmp_path):
        """Explicit workspace=None must also raise."""
        f = tmp_path / "test.md"
        f.write_text("## Test\n- content\n")

        with pytest.raises(ValueError):
            CompressionEngine.compress_file(str(f), workspace=None)


# ---------------------------------------------------------------------------
# workspace=False — explicit opt-out must succeed
# ---------------------------------------------------------------------------

class TestWorkspaceFalseOptOut:
    def test_workspace_false_reads_file(self, tmp_path):
        """workspace=False is the explicit opt-out — file must be read."""
        f = tmp_path / "test.md"
        f.write_text("## Test\n- a reasonably long point here\n")

        result = CompressionEngine.compress_file(str(f), workspace=False)
        assert "error" not in result
        assert result["original_lines"] == 2

    def test_workspace_false_allows_any_path(self, tmp_path):
        """workspace=False removes the boundary check entirely."""
        outside = tmp_path / "elsewhere" / "file.md"
        outside.parent.mkdir()
        outside.write_text("## Anywhere\n- point that is long enough\n")
        workspace = tmp_path / "memory"
        workspace.mkdir()

        # Would be blocked with workspace=str(workspace), allowed with False
        result = CompressionEngine.compress_file(str(outside), workspace=False)
        assert "error" not in result
