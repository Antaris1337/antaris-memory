"""Claim 20: Memory compression & summarization."""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Union


class CompressionEngine:
    """Compress old memories into condensed summaries."""

    @staticmethod
    def compress_file(
        file_path: str,
        workspace: Union[str, bool, None] = None,
    ) -> Dict:
        """Read a memory file and produce a compressed summary.

        Args:
            file_path: Absolute or relative path to the file to read.
            workspace: Workspace root for path-boundary enforcement.

                - **str** (recommended) — resolved *file_path* must be inside
                  this directory.  Always pass this when *file_path* could be
                  user-controlled.
                - **False** — explicit opt-out of boundary enforcement.  Makes
                  the security bypass a visible, searchable code smell rather
                  than an invisible omission.  Use only when reading from a
                  path you fully control at call time.
                - **None (default)** — raises ``ValueError``.  A missing
                  workspace is almost certainly a programming error; a warning
                  that can be silenced by ``-W ignore`` is not a security
                  control.

        Returns:
            Dict with compressed content or an ``"error"`` key on failure.

        Raises:
            ValueError: If *workspace* is ``None`` (not supplied).
        """
        resolved = Path(file_path).resolve()

        if workspace is None:
            raise ValueError(
                "compress_file() requires a workspace argument for path "
                "boundary enforcement.\n"
                "  • Pass the workspace directory (str) to restrict reads to "
                "that directory tree.\n"
                "  • Pass workspace=False to explicitly opt out of boundary "
                "enforcement when you control the path entirely."
            )
        elif workspace is not False:
            workspace_resolved = Path(workspace).resolve()
            # relative_to() raises ValueError if resolved is outside workspace.
            # str.startswith() is NOT safe: "/data/memory_backup/evil.md"
            # .startswith("/data/memory") → True even though it escapes.
            try:
                resolved.relative_to(workspace_resolved)
            except ValueError:
                return {
                    "error": f"Path traversal denied: {file_path!r} is outside workspace"
                }
        # workspace is False → unrestricted read; caller opted out explicitly.

        try:
            content = resolved.read_text()
        except (FileNotFoundError, UnicodeDecodeError):
            return {"error": f"Cannot read: {file_path}"}

        lines = content.strip().split("\n")
        headers = [line for line in lines if line.startswith("#")]
        bullets = [line.strip() for line in lines if line.strip().startswith("- ")]
        markers = ["✅", "🎯", "💰", "🚀", "Decision:", "Key:", "Result:"]
        key_lines = [
            line.strip() for line in lines
            if any(m in line for m in markers)
        ]

        seen = set()
        unique = []
        for b in bullets + key_lines:
            norm = b.lower().strip("- ").strip()
            if norm not in seen and len(norm) > 10:
                seen.add(norm)
                unique.append(b)

        return {
            "source": file_path,
            "original_lines": len(lines),
            "compressed_lines": len(headers) + len(unique),
            "compression_ratio": round(
                1 - (len(headers) + len(unique)) / max(len(lines), 1), 2
            ),
            "headers": headers,
            "key_points": unique[:30],
            "compressed_at": datetime.now().isoformat(),
        }

    @staticmethod
    def compress_old_files(memory_dir: str, days_old: int = 7) -> List[Dict]:
        """Compress daily memory files older than *days_old*."""
        path = Path(memory_dir)
        if not path.exists():
            return []

        cutoff = datetime.now() - timedelta(days=days_old)
        results = []
        for f in sorted(path.glob("*.md")):
            match = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
            if not match:
                continue
            file_date = datetime.strptime(match.group(1), "%Y-%m-%d")
            if file_date < cutoff:
                results.append(
                    CompressionEngine.compress_file(str(f), workspace=memory_dir)
                )
        return results
