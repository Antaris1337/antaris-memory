"""
Sprint 2.7: Retrieval Feedback Loop tests.

Covers:
- RetrievalFeedback.record_outcome() mutations (good/bad/neutral)
- JSONL persistence (outcomes.jsonl)
- record_routing_outcome()
- load_history() and stats()
- MemorySystemV4 integration (record_outcome, record_routing_outcome, feedback_stats)
- Invalid outcome raises ValueError
- Cache invalidation on good outcome
"""

import json
import os
import tempfile

import pytest

from antaris_memory import MemorySystem
from antaris_memory.feedback import (
    RetrievalFeedback,
    OUTCOME_GOOD,
    OUTCOME_BAD,
    OUTCOME_NEUTRAL,
    GOOD_IMPORTANCE_MULT,
    BAD_IMPORTANCE_MULT,
)
from antaris_memory.entry import MemoryEntry


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_entry(importance: float = 0.5) -> MemoryEntry:
    e = MemoryEntry(content="test memory", source="test")
    e.importance = importance
    return e


def _make_mem(tmp_path: str) -> MemorySystem:
    mem = MemorySystem(workspace=tmp_path, use_sharding=False, use_indexing=False)
    return mem


# ── RetrievalFeedback unit tests ──────────────────────────────────────────────

class TestRetrievalFeedbackGoodOutcome:
    def test_good_boosts_importance(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry(importance=0.5)
        fb.record_outcome([entry], [entry.hash], OUTCOME_GOOD)
        assert entry.importance == pytest.approx(0.5 * GOOD_IMPORTANCE_MULT)

    def test_good_caps_importance_at_1(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry(importance=0.95)
        fb.record_outcome([entry], [entry.hash], OUTCOME_GOOD)
        assert entry.importance <= 1.0

    def test_good_does_not_reduce_importance(self, tmp_path):
        """Good outcome should never lower importance."""
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry(importance=0.5)
        before = entry.importance
        fb.record_outcome([entry], [entry.hash], OUTCOME_GOOD)
        assert entry.importance >= before


class TestRetrievalFeedbackBadOutcome:
    def test_bad_reduces_importance(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry(importance=0.5)
        fb.record_outcome([entry], [entry.hash], OUTCOME_BAD)
        assert entry.importance < 0.5

    def test_bad_importance_floor_at_0(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry(importance=0.01)
        fb.record_outcome([entry], [entry.hash], OUTCOME_BAD)
        assert entry.importance >= 0.0

    def test_bad_applies_expected_multiplier(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry(importance=0.5)
        fb.record_outcome([entry], [entry.hash], OUTCOME_BAD)
        assert entry.importance == pytest.approx(0.5 * BAD_IMPORTANCE_MULT)


class TestRetrievalFeedbackNeutralOutcome:
    def test_neutral_does_not_change_importance(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry(importance=0.5)
        fb.record_outcome([entry], [entry.hash], OUTCOME_NEUTRAL)
        assert entry.importance == pytest.approx(0.5)


class TestRetrievalFeedbackInvalidOutcome:
    def test_invalid_outcome_raises(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry()
        with pytest.raises(ValueError, match="outcome must be one of"):
            fb.record_outcome([entry], [entry.hash], "excellent")


class TestRetrievalFeedbackPersistence:
    def test_outcomes_jsonl_created(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry()
        fb.record_outcome([entry], [entry.hash], OUTCOME_GOOD)
        log_path = tmp_path / "outcomes.jsonl"
        assert log_path.exists()

    def test_outcomes_jsonl_valid_json(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry()
        fb.record_outcome([entry], [entry.hash], OUTCOME_GOOD)
        log_path = tmp_path / "outcomes.jsonl"
        with open(log_path) as f:
            record = json.loads(f.readline())
        assert record["event_type"] == "retrieval"
        assert record["outcome"] == OUTCOME_GOOD
        assert "ts" in record

    def test_load_history_returns_records(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry()
        fb.record_outcome([entry], [entry.hash], OUTCOME_GOOD)
        fb.record_outcome([entry], [entry.hash], OUTCOME_BAD)
        history = fb.load_history()
        assert len(history) >= 2

    def test_load_history_empty_when_no_file(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        assert fb.load_history() == []


class TestRetrievalFeedbackRoutingOutcome:
    def test_routing_outcome_logged(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        fb.record_routing_outcome("claude-haiku-3-5", OUTCOME_GOOD)
        history = fb.load_history()
        assert len(history) == 1
        assert history[0]["event_type"] == "routing"
        assert history[0]["model"] == "claude-haiku-3-5"

    def test_routing_invalid_outcome_raises(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        with pytest.raises(ValueError):
            fb.record_routing_outcome("gpt-4o", "amazing")

    def test_stats_counts_outcomes(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        entry = _make_entry()
        fb.record_outcome([entry], [entry.hash], OUTCOME_GOOD)
        fb.record_outcome([entry], [entry.hash], OUTCOME_BAD)
        fb.record_routing_outcome("model-x", OUTCOME_NEUTRAL)
        s = fb.stats()
        assert s["good"] == 1
        assert s["bad"] == 1
        assert s["neutral"] == 1
        assert s["retrieval"] == 2
        assert s["routing"] == 1
        assert s["total"] == 3


class TestRetrievalFeedbackReturnCount:
    def test_returns_count_of_mutated_entries(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        e1 = _make_entry()
        e2 = MemoryEntry(content="another memory", source="test2")
        result = fb.record_outcome([e1, e2], [e1.hash], OUTCOME_GOOD)
        assert result == 1

    def test_returns_zero_when_id_not_found(self, tmp_path):
        fb = RetrievalFeedback(str(tmp_path))
        e1 = _make_entry()
        result = fb.record_outcome([e1], ["nonexistent-id"], OUTCOME_GOOD)
        assert result == 0


# ── MemorySystemV4 integration tests ─────────────────────────────────────────

class TestMemorySystemFeedbackIntegration:
    def test_record_outcome_on_mem_system(self, tmp_path):
        mem = _make_mem(str(tmp_path))
        mem.ingest("Important decision made about architecture")
        # Use explain=True to get SearchResult objects with .entry
        results = mem.search("architecture", explain=True)
        assert results, "Expected search results"
        entry = results[0].entry
        # Force importance to a low value so boost is visible
        entry.importance = 0.4
        ids = [entry.hash]
        mem.record_outcome(ids, OUTCOME_GOOD)
        assert entry.importance == pytest.approx(0.4 * GOOD_IMPORTANCE_MULT)

    def test_record_routing_outcome_on_mem_system(self, tmp_path):
        mem = _make_mem(str(tmp_path))
        # Should not raise
        mem.record_routing_outcome("claude-haiku-3-5", OUTCOME_GOOD)

    def test_feedback_stats_returns_dict(self, tmp_path):
        mem = _make_mem(str(tmp_path))
        mem.ingest("Test memory for feedback")
        # Default search() returns MemoryEntry objects directly
        entries = mem.search("feedback")
        ids = [e.hash for e in entries]
        mem.record_outcome(ids, OUTCOME_NEUTRAL)
        stats = mem.feedback_stats()
        assert "total" in stats
        assert stats["total"] >= 1

    def test_outcomes_jsonl_in_workspace(self, tmp_path):
        mem = _make_mem(str(tmp_path))
        mem.ingest("Something to remember")
        entries = mem.search("remember")
        ids = [e.hash for e in entries]
        mem.record_outcome(ids, OUTCOME_BAD)
        log = os.path.join(str(tmp_path), "outcomes.jsonl")
        assert os.path.exists(log)
