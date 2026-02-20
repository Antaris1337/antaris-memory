"""Tests for the production cleanup API: purge(), rebuild_indexes(),
wal_flush(), and wal_inspect().

These are the APIs that would have turned Moro's 10-step manual shard
surgery into a two-liner. Every test here maps to a real production
scenario encountered during dogfooding.

Note on test content: antaris-memory applies two filters to ingest():
  1. Length < 15 chars → skipped
  2. Gating system classifies generic/low-information text as P3 → skipped
All test fixtures use substantive, information-dense content.
"""
import pytest

from antaris_memory import MemorySystem


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    """Fresh MemorySystem backed by a temp directory."""
    mem = MemorySystem(workspace=str(tmp_path / "mem_store"))
    yield mem


def _populate(mem, entries):
    """Ingest a list of (content, source) tuples and flush the WAL."""
    for content, source in entries:
        mem.ingest(content, source=source)
    mem.save()
    return mem


# ── Test content bank — substantive strings that pass gating ─────────────────

GOOD = "Antaris memory system stores BM25-indexed episodic memories for agent recall"
GOOD2 = "AgentPipeline coordinates guard, memory, context, routing on every turn"
PIPELINE_BAD = "pipeline:pipeline_abc123 ingested conversation metadata untrusted blocks"
PIPELINE_BAD2 = "more pipeline noise — untrusted Conversation info metadata was stored here"
OPENCLAW_AUTO = "openclaw:auto ingested symlink mismatch debug entry from antaris plugin"
SYMLINK_NOISE = "symlink mismatch fixed in antaris-openclaw-plugin extension directory"
UNTRUSTED_META = "Conversation info (untrusted metadata) discord channel sender label block"
UNTRUSTED_META2 = "Sender (untrusted metadata) username antaris tag stored by pipeline bridge"
ROUTING_MEMORY = "User requested routing optimization for Claude claude-3-opus production agent"
STALE = "this stale pipeline entry should be purged from the antaris memory store"
CLEAN = "this clean user entry should survive purge and remain in memory store"
FILTER_MATCH = "this specific memory was created by the pipeline filter function test case"
UNTOUCHED = "antaris router selected claude-3-sonnet for this low-complexity inference task"
KEEP_AROUND = "antaris memory pipeline keeps important context across agent conversation turns"
REMOVE_NOW = "remove this pipeline memory artifact from the antaris store immediately please"
BAD_WAL = "bad wal entry from pipeline bad session should not replay after purge filter"
GOOD_WAL = "good wal entry for user session should persist after pipeline purge runs"
FLUSH_ENTRY = "flush test entry verifies WAL compaction to shards for persistence check here"
INDEXING = "test memory entry for index rebuild operations on antaris memory store shards"
SEARCH1 = "antaris memory system benchmarks show 180x faster search than mem0 baseline"
SEARCH2 = "routing strategies for cost optimization in production agent deployments here"
SPY_ENTRY = "antaris-suite plugin ingested this entry during before_agent_start hook call"
SOURCE_MATCH = "this entry from pipeline session matches source pattern for purge operation"
CONTENT_XYZ = "this content xyz pattern appears in entry and should trigger purge filter"
SAFE = "this safe antaris memory entry should definitely survive after purge runs here"
SURVIVES = "this memory definitely survives the purge operation and stays in the store"
REMOVED_NOW = "this memory should be removed from antaris store by purge source filter now"


# ── purge(source=...) ─────────────────────────────────────────────────────────

class TestPurgeBySource:
    def test_exact_source_match(self, store):
        _populate(store, [
            (GOOD, "user:session_1"),
            (PIPELINE_BAD, "pipeline:pipeline_abc123"),
            (PIPELINE_BAD2, "pipeline:pipeline_abc123"),
        ])
        result = store.purge(source="pipeline:pipeline_abc123")
        store.save()

        assert result["removed"] == 2
        remaining = store.search("pipeline abc123", limit=10)
        assert not any("pipeline:pipeline_abc123" in r.content for r in remaining)

    def test_glob_wildcard_source(self, store):
        _populate(store, [
            (GOOD, "user:session_1"),
            (PIPELINE_BAD, "pipeline:pipeline_aaa111"),
            (PIPELINE_BAD2, "pipeline:pipeline_bbb222"),
        ])
        result = store.purge(source="pipeline:pipeline_*")
        store.save()

        assert result["removed"] == 2

    def test_glob_prefix_source_pattern(self, store):
        _populate(store, [
            (OPENCLAW_AUTO, "openclaw:auto"),
            (ROUTING_MEMORY, "user:manual"),
            (PIPELINE_BAD, "pipeline:pipeline_xyz"),
        ])
        result = store.purge(source="openclaw:*")
        store.save()

        assert result["removed"] == 1

    def test_no_source_match_removes_nothing(self, store):
        _populate(store, [(GOOD, "user:session")])
        result = store.purge(source="nonexistent:source_pattern_*")
        assert result["removed"] == 0
        assert result["total"] == 0

    def test_returns_correct_count_and_audit(self, store):
        _populate(store, [
            (PIPELINE_BAD, "pipeline:pipeline_1"),
            (PIPELINE_BAD2, "pipeline:pipeline_1"),
            (GOOD, "user:keep"),
        ])
        result = store.purge(source="pipeline:pipeline_1")
        assert result["removed"] == 2
        assert "audit" in result
        assert result["audit"]["count"] >= 2

    def test_kept_memories_survive(self, store):
        _populate(store, [
            (SURVIVES, "user:keep"),
            (PIPELINE_BAD, "pipeline:pipeline_rm"),
        ])
        store.purge(source="pipeline:pipeline_rm")
        store.save()

        results = store.search("survives the purge operation", limit=5)
        assert any("survives" in r.content for r in results)


# ── purge(filter_fn=...) ─────────────────────────────────────────────────────

class TestPurgeByFilterFn:
    def test_filter_by_content_pattern(self, store):
        _populate(store, [
            (UNTRUSTED_META, "pipeline:p1"),
            (ROUTING_MEMORY, "pipeline:p1"),
            (UNTRUSTED_META2, "pipeline:p1"),
        ])
        result = store.purge(
            filter_fn=lambda e: "untrusted metadata" in e.content
        )
        store.save()

        assert result["removed"] == 2
        remaining = store.search("routing optimization claude", limit=5)
        assert any("routing" in r.content for r in remaining)

    def test_filter_fn_exception_is_swallowed(self, store):
        """A buggy filter_fn should not crash purge() — it degrades gracefully."""
        _populate(store, [(SAFE, "user:1")])

        def bad_fn(e):
            raise ValueError("intentional error in filter function")

        result = store.purge(filter_fn=bad_fn)
        assert result["removed"] == 0

    def test_filter_fn_receives_memory_entry_attributes(self, store):
        """Verify filter_fn receives objects with .source and .content attrs."""
        seen = []
        _populate(store, [(SPY_ENTRY, "user:test_source")])

        def spy(e):
            seen.append((e.source, e.content))
            return False  # keep everything

        store.purge(filter_fn=spy)
        assert len(seen) >= 1
        assert any(src == "user:test_source" for src, _ in seen)


# ── purge(content_contains=...) ──────────────────────────────────────────────

class TestPurgeByContentContains:
    def test_removes_matching_content(self, store):
        _populate(store, [
            (SYMLINK_NOISE, "openclaw:auto"),
            (ROUTING_MEMORY, "user:session"),
        ])
        result = store.purge(content_contains="symlink mismatch")
        store.save()

        assert result["removed"] == 1

    def test_case_insensitive_matching(self, store):
        _populate(store, [
            (UNTRUSTED_META, "pipeline:p"),
            (GOOD, "user:u"),
        ])
        result = store.purge(content_contains="UNTRUSTED METADATA")
        assert result["removed"] == 1

    def test_no_match_removes_nothing(self, store):
        _populate(store, [(SAFE, "user:u")])
        result = store.purge(content_contains="xyz_nonexistent_pattern_xyz")
        assert result["removed"] == 0


# ── OR logic (multiple criteria) ─────────────────────────────────────────────

class TestPurgeCombinedCriteria:
    def test_or_logic_source_and_content(self, store):
        _populate(store, [
            (OPENCLAW_AUTO, "openclaw:auto"),   # matches source
            (SYMLINK_NOISE, "user:session"),     # matches content_contains
            (SURVIVES, "user:session"),          # matches neither — survives
        ])
        result = store.purge(
            source="openclaw:auto",
            content_contains="symlink mismatch",
        )
        store.save()

        assert result["removed"] == 2
        remaining = store.search("survives the purge operation", limit=5)
        assert any("survives" in r.content for r in remaining)

    def test_all_three_criteria_combined(self, store):
        _populate(store, [
            (SOURCE_MATCH, "pipeline:pipeline_x"),       # source
            (CONTENT_XYZ, "user:u1"),                    # content_contains
            (FILTER_MATCH, "user:u2"),                   # filter_fn
            (UNTOUCHED, "user:u3"),                      # matches nothing
        ])
        result = store.purge(
            source="pipeline:pipeline_x",
            content_contains="xyz pattern",
            filter_fn=lambda e: "filter function test case" in e.content,
        )
        assert result["removed"] == 3


# ── WAL filtering ─────────────────────────────────────────────────────────────

class TestPurgeWAL:
    def test_wal_entries_are_filtered_on_purge(self, store):
        """Purged entries in the WAL should not come back on next load."""
        store.ingest(BAD_WAL, source="pipeline:pipeline_bad")
        store.ingest(GOOD_WAL, source="user:keep")

        result = store.purge(source="pipeline:pipeline_bad")
        store.save()

        fresh = MemorySystem(workspace=store.workspace)
        results = fresh.search("bad wal entry pipeline bad session", limit=5)
        assert not any("bad wal entry" in r.content for r in results)

    def test_wal_inspect_shows_pending_info_when_empty(self, store):
        """wal_inspect() reports stats without mutating state."""
        info = store.wal_inspect()
        assert info["pending_entries"] == 0
        assert "size_bytes" in info
        assert isinstance(info["sample"], list)

    def test_wal_inspect_after_ingest_has_correct_keys(self, store):
        store.ingest(SEARCH1, source="user:1")
        store.ingest(SEARCH2, source="user:2")
        info = store.wal_inspect()
        assert "pending_entries" in info
        assert "size_bytes" in info
        assert isinstance(info["sample"], list)

    def test_wal_flush_persists_entries_to_shards(self, store):
        """wal_flush() should write WAL entries to shards."""
        store.ingest(FLUSH_ENTRY, source="user:flush")
        store.wal_flush()

        fresh = MemorySystem(workspace=store.workspace)
        results = fresh.search("flush test entry verifies WAL compaction", limit=5)
        assert any("flush test entry" in r.content for r in results)


# ── rebuild_indexes() ─────────────────────────────────────────────────────────

class TestRebuildIndexes:
    def test_returns_summary_with_memory_count(self, store):
        _populate(store, [(INDEXING, "user:u")])
        result = store.rebuild_indexes()

        assert "memories" in result
        assert result["memories"] >= 1

    def test_search_works_after_rebuild(self, store):
        _populate(store, [
            (SEARCH1, "user:u"),
            (SEARCH2, "user:u"),
        ])
        store.rebuild_indexes()

        results = store.search("antaris memory benchmarks", limit=5)
        assert any("antaris" in r.content for r in results)

    def test_rebuild_after_purge_removes_stale_references(self, store):
        """After purging and rebuilding, search should not return purged entries."""
        _populate(store, [
            (STALE, "pipeline:pipeline_stale"),
            (CLEAN, "user:keep"),
        ])
        store.purge(source="pipeline:pipeline_stale")
        store.rebuild_indexes()
        store.save()

        results = store.search("stale pipeline entry purged", limit=10)
        assert not any("stale pipeline entry" in r.content for r in results)


# ── No-arg guard ─────────────────────────────────────────────────────────────

class TestPurgeGuards:
    def test_no_args_returns_zero_removed(self, store):
        _populate(store, [(SAFE, "user:u")])
        result = store.purge()
        assert result["removed"] == 0
        assert result["total"] == 0

    def test_purge_does_not_break_subsequent_searches(self, store):
        _populate(store, [
            (SURVIVES, "user:u"),
            (REMOVED_NOW, "pipeline:pipeline_x"),
        ])
        store.purge(source="pipeline:pipeline_x")
        store.save()

        results = store.search("survives the purge operation and stays", limit=5)
        assert any("survives" in r.content for r in results)

    def test_purge_returns_dict_with_expected_keys(self, store):
        result = store.purge(source="nonexistent:*")
        assert set(result.keys()) >= {"removed", "wal_removed", "total", "audit"}
