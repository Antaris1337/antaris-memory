"""
Sprint 2.8 — bulk_ingest() and bulk_mode() tests

Covers:
  1. Basic bulk_ingest with string list
  2. bulk_ingest with dict entries
  3. bulk_ingest with mixed str/dict entries
  4. Count returned equals items actually ingested
  5. Deduplication inside bulk_ingest (same content twice)
  6. Single rebuild_indexes call confirmed (mock)
  7. Backward compat: existing ingest() unchanged after bulk
  8. bulk_mode() context manager basic usage
  9. bulk_mode() defers rebuilds during ingest
 10. bulk_mode(): index rebuild fires exactly once on exit
 11. bulk_ingest with empty list returns 0
 12. bulk_ingest with noise-only content returns 0
 13. bulk_ingest with dict missing content key is skipped
 14. bulk_ingest persists to disk (searchable after)
 15. bulk_ingest handles large batch (1000 items) without error
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

from antaris_memory import MemorySystem


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_mem(tmp_dir, **kwargs):
    return MemorySystem(workspace=tmp_dir, **kwargs)


def _content(i: int) -> str:
    return f"Bulk ingest test memory entry number {i} with enough characters to pass gating"


def _dict_entry(i: int, **overrides) -> dict:
    base = {
        "content": _content(i),
        "source": "test-source",
        "category": "technical",
        "memory_type": "fact",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBulkIngest(unittest.TestCase):

    # ── 1. Basic bulk_ingest with string list ────────────────────────────────
    def test_basic_string_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            entries = [_content(i) for i in range(10)]
            count = mem.bulk_ingest(entries)
            self.assertGreater(count, 0)
            self.assertLessEqual(count, 10)

    # ── 2. bulk_ingest with dict entries ────────────────────────────────────
    def test_dict_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            entries = [_dict_entry(i) for i in range(5)]
            count = mem.bulk_ingest(entries)
            self.assertGreater(count, 0)
            self.assertEqual(count, len(mem.memories))

    # ── 3. Mixed str/dict entries ────────────────────────────────────────────
    def test_mixed_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            entries = [
                _content(0),
                _dict_entry(1),
                _content(2),
                _dict_entry(3, memory_type="procedure"),
            ]
            count = mem.bulk_ingest(entries)
            self.assertGreater(count, 0)

    # ── 4. Count returned equals items ingested ──────────────────────────────
    def test_count_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            entries = [_content(i) for i in range(20)]
            count = mem.bulk_ingest(entries)
            # Count must match the actual in-memory count
            self.assertEqual(count, len(mem.memories))

    # ── 5. Deduplication inside bulk_ingest ─────────────────────────────────
    def test_deduplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            same_content = _content(99)
            entries = [same_content, same_content, same_content]
            count = mem.bulk_ingest(entries)
            # Only one copy should be stored
            self.assertEqual(count, 1)

    # ── 6. Single rebuild_indexes confirmed via mock ─────────────────────────
    def test_single_rebuild_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            # Patch rebuild_indexes to count calls
            original_rebuild = mem.index_manager.rebuild_indexes
            call_count = {"n": 0}

            def counting_rebuild(memories):
                call_count["n"] += 1
                return original_rebuild(memories)

            mem.index_manager.rebuild_indexes = counting_rebuild

            # Ingest 200 entries — without bulk_ingest this would trigger
            # multiple auto-flushes, each calling rebuild_indexes
            entries = [_content(i) for i in range(200)]
            mem.bulk_ingest(entries)

            # Only ONE rebuild should have occurred (at the end)
            self.assertEqual(call_count["n"], 1,
                             f"Expected 1 rebuild call, got {call_count['n']}")

    # ── 7. Backward compat: ingest() works normally after bulk ───────────────
    def test_backward_compat_after_bulk(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            mem.bulk_ingest([_content(i) for i in range(5)])
            before = len(mem.memories)
            # Normal ingest should still work
            added = mem.ingest(_content(999))
            self.assertGreaterEqual(added, 0)
            # Bulk mode flag must be off
            self.assertFalse(mem._bulk_mode_active)

    # ── 8. bulk_mode() context manager basic usage ──────────────────────────
    def test_bulk_mode_basic(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            with mem.bulk_mode():
                for i in range(10):
                    mem.ingest(_content(i))
            self.assertGreater(len(mem.memories), 0)
            self.assertFalse(mem._bulk_mode_active)

    # ── 9. bulk_mode() defers rebuilds during ingest ─────────────────────────
    def test_bulk_mode_defers_during_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            rebuild_calls_during = []

            original_rebuild = mem.index_manager.rebuild_indexes

            def tracking_rebuild(memories):
                rebuild_calls_during.append(mem._bulk_mode_active)
                return original_rebuild(memories)

            mem.index_manager.rebuild_indexes = tracking_rebuild

            with mem.bulk_mode():
                for i in range(200):
                    mem.ingest(_content(i))

            # Any rebuild during context must have bulk_mode_active=True
            # (i.e. no rebuild occurred during the bulk phase itself)
            # Rebuilds tracked inside context should all be False (only
            # the final rebuild runs after bulk_mode_active is set to False)
            for was_bulk in rebuild_calls_during:
                self.assertFalse(was_bulk,
                    "rebuild_indexes was called while _bulk_mode_active=True — "
                    "this is the O(n²) regression we're fixing!")

    # ── 10. bulk_mode() index rebuild fires exactly once on exit ─────────────
    def test_bulk_mode_single_rebuild_on_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            call_count = {"n": 0}
            original_rebuild = mem.index_manager.rebuild_indexes

            def counting_rebuild(memories):
                call_count["n"] += 1
                return original_rebuild(memories)

            mem.index_manager.rebuild_indexes = counting_rebuild

            with mem.bulk_mode():
                for i in range(200):
                    mem.ingest(_content(i))

            self.assertEqual(call_count["n"], 1,
                             f"Expected 1 rebuild on exit, got {call_count['n']}")

    # ── 11. bulk_ingest with empty list returns 0 ────────────────────────────
    def test_empty_list_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            count = mem.bulk_ingest([])
            self.assertEqual(count, 0)

    # ── 12. bulk_ingest with noise-only content returns 0 ────────────────────
    def test_noise_content_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            # Very short lines that fail the 15-char minimum
            noise = ["hi", "ok", "yes", "no", "---", "```python"]
            count = mem.bulk_ingest(noise)
            self.assertEqual(count, 0)

    # ── 13. Dict with missing content key is skipped ─────────────────────────
    def test_dict_missing_content_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            entries = [
                {"source": "test", "category": "general"},  # no content
                {"content": "", "source": "test"},           # empty content
                _content(1),                                 # valid string
            ]
            count = mem.bulk_ingest(entries)
            # Only the valid string should be ingested
            self.assertEqual(count, 1)

    # ── 14. bulk_ingest persists to disk (searchable after) ──────────────────
    def test_persists_and_searchable(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            unique_keyword = "xenomorphic_performance_marker"
            entries = [
                f"The {unique_keyword} system test entry with sufficient length to be stored properly.",
            ]
            count = mem.bulk_ingest(entries)
            self.assertGreater(count, 0)
            results = mem.search(unique_keyword, limit=5)
            self.assertGreater(len(results), 0)
            self.assertIn(unique_keyword, results[0].content)

    # ── 15. Large batch (1000 items) without error ───────────────────────────
    def test_large_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _make_mem(tmp)
            entries = [_content(i) for i in range(1000)]
            count = mem.bulk_ingest(entries)
            self.assertGreater(count, 0)
            self.assertFalse(mem._bulk_mode_active)


if __name__ == "__main__":
    unittest.main()
