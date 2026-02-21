"""
Antaris Memory MCP Server

Exposes antaris-memory as MCP resources and tools for any MCP-enabled agent.

Resources:
  - antaris://memory/{query} → relevant memories for query

Tools:
  - recall_memories(query, limit) → search and return memories
  - store_memory(content, category, tags) → ingest a new memory
  - memory_stats() → storage statistics

Usage:
    python -m antaris_memory.mcp_server --memory-path ./my_memory_store
    # or
    from antaris_memory.mcp_server import create_server

Concurrency note
----------------
The module-level cache holds one live ``MemorySystem`` per resolved path.
Cache entries are invalidated when the workspace's mtime advances — meaning
writes from another process (a second agent, a CLI tool) are detected on the
next call.  Same-process writes are always visible immediately since the cache
holds the live mutated instance.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Graceful MCP availability check
# ---------------------------------------------------------------------------
try:
    from mcp.server.fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None  # type: ignore

from antaris_memory import MemorySystem

# ---------------------------------------------------------------------------
# Module-level cache — one MemorySystem per resolved path
# ---------------------------------------------------------------------------
# _MEMORY_CACHE   : live MemorySystem instance keyed by resolved path
# _CACHE_MTIME    : workspace mtime at last cache fill, keyed by resolved path
#
# Mtime-based invalidation (NI2): every _load_memory() call checks whether
# the workspace directory or shards subdirectory has been modified since the
# last fill.  If so, the cache is dropped and the corpus is reloaded from
# disk.  This detects writes from external processes without requiring a TTL
# or shared lock.

_MEMORY_CACHE: Dict[str, MemorySystem] = {}
_CACHE_MTIME: Dict[str, float] = {}


def _workspace_mtime(resolved_path: str) -> float:
    """Return the most recent mtime across the workspace root and shards dir."""
    mtimes: List[float] = []
    for candidate in (
        resolved_path,
        os.path.join(resolved_path, "shards"),
    ):
        try:
            mtimes.append(os.path.getmtime(candidate))
        except OSError:
            pass
    return max(mtimes) if mtimes else 0.0


def _invalidate_cache(resolved_path: str) -> None:
    """Explicitly drop the cached instance for *resolved_path*.

    Rarely needed in normal use — the mtime check in ``_load_memory`` handles
    cross-process invalidation automatically.  Call this if you need to force
    an immediate reload (e.g., in tests or after an out-of-band migration).
    """
    _MEMORY_CACHE.pop(resolved_path, None)
    _CACHE_MTIME.pop(resolved_path, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_memory_path(memory_path: Optional[str] = None) -> str:
    """Resolve memory path from arg, env, or default."""
    return (
        memory_path
        or os.environ.get("ANTARIS_MEMORY_PATH")
        or "./antaris_memory_store"
    )


def _load_memory(memory_path: str) -> MemorySystem:
    """Return a MemorySystem for *memory_path*, reloading if the workspace changed.

    The cached instance is reused across calls (no repeated disk deserialisation).
    If the workspace mtime has advanced since the last fill — indicating that
    another process wrote to the store — the cache entry is dropped and the
    corpus is reloaded fresh.
    """
    resolved = os.path.abspath(memory_path)
    current_mtime = _workspace_mtime(resolved)
    cached_mtime = _CACHE_MTIME.get(resolved, -1.0)

    if resolved not in _MEMORY_CACHE or current_mtime > cached_mtime:
        mem = MemorySystem(resolved)
        mem.load()
        _MEMORY_CACHE[resolved] = mem
        # NI2-FLOW: re-sample mtime AFTER loading to shrink the TOCTOU window.
        # Stamping current_mtime (sampled before the load) would record a
        # pre-write timestamp if another process wrote between sample and load,
        # causing the next call to see no advancement and serve stale data.
        _CACHE_MTIME[resolved] = _workspace_mtime(resolved)

    return _MEMORY_CACHE[resolved]


def _result_to_dict(result: Any) -> Dict[str, Any]:
    """Convert a SearchResult (explain=True) or MemoryEntry to a serialisable dict.

    When called with a ``SearchResult`` object the ``relevance`` field reflects
    the actual query-time BM25/cosine score, not the stored importance weight.
    Both values are included so callers can choose which to display or rank by.
    """
    if hasattr(result, "entry") and hasattr(result, "score"):
        # SearchResult from search(explain=True)
        entry = result.entry
        relevance = round(float(result.relevance), 4)   # query-time relevance (0–1)
        score = round(float(result.score), 6)            # raw BM25/hybrid score
    else:
        # Fallback: plain MemoryEntry (legacy / non-indexed path, or future code
        # that forgets explain=True).  Do NOT use confidence here — confidence
        # is epistemological certainty (how reliable is this memory), not
        # query-time relevance.  A low-confidence memory about a highly relevant
        # topic would be ranked lower than it deserves.  importance is the
        # least-wrong proxy: long-term value shaped by feedback and decay.
        entry = result
        relevance = round(float(getattr(entry, "importance", 1.0)), 4)
        score = relevance

    return {
        "content": getattr(entry, "content", ""),
        "category": getattr(entry, "category", "general"),
        "relevance": relevance,   # query-time relevance — use this for ranking
        "score": score,           # raw search score
        "importance": round(float(getattr(entry, "importance", 1.0)), 4),  # stored weight
        "source": getattr(entry, "source", ""),
        "memory_type": getattr(entry, "memory_type", "episodic"),
    }


def _format_memory_block(results: list, query: str) -> str:
    """Format search results as a readable memory context block."""
    if not results:
        return f"[antaris-memory] No memories found for query: {query!r}"

    lines = [f"[antaris-memory] {len(results)} memories for query: {query!r}", ""]
    for i, r in enumerate(results, 1):
        d = _result_to_dict(r)
        lines.append(
            f"{i}. [{d['category']}] {d['content']}"
            f"  (relevance={d['relevance']}, type={d['memory_type']})"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

def create_server(memory_path: Optional[str] = None) -> "FastMCP":
    """Create and return the FastMCP server with antaris-memory tools/resources.

    Args:
        memory_path: Path to the memory workspace directory.  Falls back to
            ``$ANTARIS_MEMORY_PATH`` env var, then ``./antaris_memory_store``.

    Returns:
        A configured ``FastMCP`` instance ready to run.

    Raises:
        ImportError: If the ``mcp`` package is not installed.
    """
    if not MCP_AVAILABLE:
        raise ImportError(
            "The 'mcp' package is required to run the antaris-memory MCP server. "
            "Install it with: pip install mcp"
        )

    resolved_path = _get_memory_path(memory_path)
    mcp = FastMCP(
        name="antaris-memory",
        instructions=(
            "Antaris Memory — persistent agent memory. "
            "Use recall_memories to search past context, store_memory to save new information, "
            "and memory_stats to inspect the store."
        ),
    )

    # ------------------------------------------------------------------
    # Tool: recall_memories
    # ------------------------------------------------------------------
    @mcp.tool()
    def recall_memories(query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search agent memories and return the most relevant results.

        Args:
            query: Natural-language search query.
            limit: Maximum number of memories to return (default 5).

        Returns:
            List of memory dicts with keys: content, category, relevance,
            score, importance, source, memory_type.
            ``relevance`` is the query-time BM25/cosine score (0–1).
            ``importance`` is the stored long-term weight (affected by
            feedback and decay).  Empty list if nothing matches.
        """
        mem = _load_memory(resolved_path)
        # explain=True returns SearchResult objects with .score and .relevance
        # so _result_to_dict can expose the actual query-time relevance score
        # rather than the stored importance weight (NW2 fix).
        # NW1 fix: read operations do NOT call mem.save().  Decay-state updates
        # (last_accessed, access_count) are held in memory and persisted the
        # next time store_memory() or an explicit save() is called.  This
        # eliminates write-amplification at 10K+ entries.
        results = mem.search(query=query, limit=limit, use_decay=True, explain=True)
        if not results:
            return []
        return [_result_to_dict(r) for r in results]

    # ------------------------------------------------------------------
    # Tool: store_memory
    # ------------------------------------------------------------------
    @mcp.tool()
    def store_memory(
        content: str,
        category: str = "general",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Ingest new information into persistent agent memory.

        Args:
            content: Text to store (multi-line supported).
            category: Category label, e.g. "strategic", "tactical", "general".
            tags: Optional list of tag strings to associate with this memory.

        Returns:
            Dict with keys: stored (bool), entry_count (int).
        """
        mem = _load_memory(resolved_path)
        added = mem.ingest(content=content, category=category, tags=tags or None)
        mem.save()
        # Update the cached mtime so the next _load_memory() doesn't evict the
        # instance we just wrote through (the workspace mtime just advanced).
        _CACHE_MTIME[resolved_path] = _workspace_mtime(resolved_path)
        return {
            "stored": added > 0,
            "entry_count": len(mem.memories),
        }

    # ------------------------------------------------------------------
    # Tool: memory_stats
    # ------------------------------------------------------------------
    @mcp.tool()
    def memory_stats() -> Dict[str, Any]:
        """Return statistics about the memory store.

        Returns:
            Dict with keys: total_memories, categories, disk_usage_mb,
            avg_score, avg_confidence, cache_hit_rate, plus additional
            performance metrics from the Sprint 11 engine.
        """
        mem = _load_memory(resolved_path)
        raw = mem.stats()
        return {
            "total_memories": raw.get("total_entries", raw.get("total", 0)),
            "categories": raw.get("categories", {}),
            "disk_usage_mb": raw.get("disk_usage_mb", 0.0),
            "avg_score": raw.get("avg_score", 0.0),
            "avg_confidence": raw.get("avg_confidence", 0.0),
            "cache_hit_rate": raw.get("cache_hit_rate", 0.0),
            "wal_pending": raw.get("wal_pending_entries", 0),
            "search_count": raw.get("search_count", 0),
        }

    # ------------------------------------------------------------------
    # Resource: antaris://memory/{query}
    # ------------------------------------------------------------------
    @mcp.resource("antaris://memory/{query}")
    def memory_resource(query: str) -> str:
        """Retrieve memories matching *query* as a formatted context block.

        URI: ``antaris://memory/<url-encoded-query>``

        Returns a human-readable block of the top matching memories, suitable
        for injecting directly into an LLM context window.
        NW1 fix: does not persist after a read-only search.
        """
        mem = _load_memory(resolved_path)
        results = mem.search(query=query, limit=10, use_decay=True, explain=True)
        return _format_memory_block(results, query)

    return mcp


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the antaris-memory MCP server (stdio transport by default)."""
    parser = argparse.ArgumentParser(
        description="Antaris Memory MCP Server — expose agent memory over MCP."
    )
    parser.add_argument(
        "--memory-path",
        default=None,
        help=(
            "Path to the memory workspace directory. "
            "Defaults to $ANTARIS_MEMORY_PATH or ./antaris_memory_store"
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for SSE transport (default: 8765).",
    )
    args = parser.parse_args()

    if not MCP_AVAILABLE:
        print(
            "ERROR: The 'mcp' package is not installed.\n"
            "Install it with: pip install mcp",
            file=sys.stderr,
        )
        sys.exit(1)

    server = create_server(memory_path=args.memory_path)

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.settings.host = args.host
        server.settings.port = args.port
        server.run(transport="sse")


if __name__ == "__main__":
    main()
