"""
MemorySystem — the main interface to antaris-memory.

Usage:
    from antaris_memory import MemorySystem

    mem = MemorySystem("./workspace")
    mem.ingest_file("notes.md", category="tactical")
    mem.ingest_directory("./memory", category="tactical")
    results = mem.search("patent filing")
    mem.save()
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .entry import MemoryEntry
from .decay import DecayEngine
from .sentiment import SentimentTagger
from .temporal import TemporalEngine
from .confidence import ConfidenceEngine
from .compression import CompressionEngine
from .forgetting import ForgettingEngine
from .consolidation import ConsolidationEngine
from .gating import InputGate
from .synthesis import KnowledgeSynthesizer

# Default tags to auto-extract
_DEFAULT_TAG_TERMS = [
    "web3", "ethereum", "postgresql", "optimization", "cost",
    "revenue", "security", "deployment", "production", "testing",
]


class MemorySystem:
    """Complete memory system with decay, sentiment, gating, and synthesis.

    Parameters
    ----------
    workspace : str
        Root directory. Metadata files are stored here.
    half_life : float
        Decay half-life in days (default 7).
    tag_terms : list[str] | None
        Custom terms to auto-tag. Merged with built-in defaults.
    """

    def __init__(
        self,
        workspace: str = ".",
        half_life: float = 7.0,
        tag_terms: List[str] = None,
    ):
        self.workspace = os.path.abspath(workspace)
        self.metadata_path = os.path.join(self.workspace, "memory_metadata.json")
        self.audit_path = os.path.join(self.workspace, "memory_audit.json")

        # Engines
        self.decay = DecayEngine(half_life=half_life)
        self.sentiment = SentimentTagger()
        self.temporal = TemporalEngine()
        self.confidence = ConfidenceEngine()
        self.compression = CompressionEngine()
        self.forgetting = ForgettingEngine()
        self.consolidation = ConsolidationEngine(decay=self.decay)
        self.gating = InputGate()
        self.synthesis = KnowledgeSynthesizer()

        # Tag terms
        self._tag_terms = list(set(_DEFAULT_TAG_TERMS + (tag_terms or [])))

        # Memory store
        self.memories: List[MemoryEntry] = []
        self._hashes: set = set()

    # ── persistence ─────────────────────────────────────────────────────

    def save(self) -> str:
        """Write memory state to disk. Returns path."""
        data = {
            "version": "0.2.0",
            "saved_at": datetime.now().isoformat(),
            "count": len(self.memories),
            "memories": [m.to_dict() for m in self.memories],
        }
        with open(self.metadata_path, "w") as f:
            json.dump(data, f, indent=2)
        return self.metadata_path

    def load(self) -> int:
        """Load memory state from disk. Returns count loaded."""
        if not os.path.exists(self.metadata_path):
            return 0
        with open(self.metadata_path) as f:
            data = json.load(f)
        self.memories = [MemoryEntry.from_dict(d) for d in data.get("memories", [])]
        self._hashes = {m.hash for m in self.memories}
        return len(self.memories)

    # ── ingestion ───────────────────────────────────────────────────────

    def ingest(self, content: str, source: str = "inline",
               category: str = "general") -> int:
        """Ingest raw text. Returns count of new memories added."""
        count = 0
        for i, line in enumerate(content.split("\n")):
            stripped = line.strip()
            if len(stripped) < 15 or stripped.startswith("```") or stripped == "---":
                continue
            entry = MemoryEntry(stripped, source, i + 1, category)
            if entry.hash in self._hashes:
                continue
            entry.tags = self._extract_tags(stripped)
            entry.sentiment = self.sentiment.analyze(stripped)
            if category == "strategic":
                entry.confidence = 0.8
            elif category in ("operational", "business"):
                entry.confidence = 0.6
            self.memories.append(entry)
            self._hashes.add(entry.hash)
            count += 1
        return count

    def ingest_file(self, path: str, category: str = "general") -> int:
        """Ingest a single file."""
        try:
            content = Path(path).read_text(errors="replace")
        except FileNotFoundError:
            return 0
        return self.ingest(content, source=path, category=category)

    def ingest_directory(self, directory: str, pattern: str = "*.md",
                         category: str = "general") -> int:
        """Ingest all matching files in a directory."""
        d = Path(directory)
        if not d.exists():
            return 0
        count = 0
        for f in sorted(d.glob(pattern)):
            count += self.ingest_file(str(f), category=category)
        return count

    def ingest_with_gating(self, content: str, source: str = "inline", context: Dict = None) -> int:
        """Ingest content with automatic priority-based routing and filtering.
        
        P3 (ephemeral) content is silently dropped. P0-P2 content is stored
        with appropriate category assignment.
        
        Returns count of new memories added (P3 content doesn't count).
        """
        count = 0
        for i, line in enumerate(content.split("\n")):
            stripped = line.strip()
            if len(stripped) < 5:  # Skip very short lines
                continue
                
            # Use gating system to classify and route
            gate_context = context or {}
            gate_context.update({"source": source, "line": i + 1})
            routing = self.gating.route(stripped, gate_context)
            
            # Skip P3 ephemeral content
            if not routing["store"]:
                continue
                
            # Check for duplicates
            entry = MemoryEntry(stripped, source, i + 1, routing["category"])
            if entry.hash in self._hashes:
                continue
                
            # Apply standard processing
            entry.tags = self._extract_tags(stripped)
            entry.sentiment = self.sentiment.analyze(stripped)
            
            # Set confidence based on priority
            if routing["priority"] == "P0":
                entry.confidence = 0.9  # High confidence for critical items
            elif routing["priority"] == "P1":
                entry.confidence = 0.7  # Good confidence for operational items
            else:  # P2
                entry.confidence = 0.5  # Standard confidence for contextual items
                
            entry.tags.append(routing["priority"])  # Add priority as tag
            
            self.memories.append(entry)
            self._hashes.add(entry.hash)
            count += 1
            
        return count

    # ── search ──────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        limit: int = 20,
        category: str = None,
        min_confidence: float = 0.0,
        sentiment_filter: str = None,
    ) -> List[MemoryEntry]:
        """Search memories. Results weighted by relevance × decay score."""
        q = query.lower()
        q_words = set(re.findall(r"\w{3,}", q))
        results = []

        for m in self.memories:
            if category and m.category != category:
                continue
            if min_confidence and m.confidence < min_confidence:
                continue
            if sentiment_filter and sentiment_filter not in m.sentiment:
                continue

            c = m.content.lower()
            score = 0.0
            if q in c:
                score += 3.0
            else:
                c_words = set(re.findall(r"\w{3,}", c))
                overlap = len(q_words & c_words) / max(len(q_words), 1)
                score += overlap * 2.0

            tag_hits = sum(1 for t in m.tags if q in t.lower())
            score += tag_hits * 0.5

            decay_score = self.decay.score(m)
            score *= (0.5 + decay_score)

            if score > 0.3:
                results.append((m, score))
                self.decay.reinforce(m)

        results.sort(key=lambda x: x[1], reverse=True)
        return [m for m, _ in results[:limit]]

    # ── temporal queries ────────────────────────────────────────────────

    def on_date(self, date: str) -> List[MemoryEntry]:
        return self.temporal.on_date(self.memories, date)

    def between(self, start: str, end: str) -> List[MemoryEntry]:
        return self.temporal.between(self.memories, start, end)

    def narrative(self, topic: str = None) -> str:
        return self.temporal.narrative(self.memories, topic)

    # ── forgetting ──────────────────────────────────────────────────────

    def forget(self, topic: str = None, entity: str = None,
               before_date: str = None) -> Dict:
        """Selectively forget memories. Returns audit log."""
        if topic:
            self.memories, gone = self.forgetting.forget_topic(self.memories, topic)
        elif entity:
            self.memories, gone = self.forgetting.forget_entity(self.memories, entity)
        elif before_date:
            self.memories, gone = self.forgetting.forget_before(self.memories, before_date)
        else:
            return {"error": "Specify topic, entity, or before_date"}

        self._hashes = {m.hash for m in self.memories}
        audit = self.forgetting.audit_log(gone)
        self._append_audit(audit)
        return audit

    # ── consolidation ───────────────────────────────────────────────────

    def consolidate(self) -> Dict:
        """Run dream-state consolidation. Returns report."""
        return self.consolidation.run(self.memories)

    def compress_old(self, days: int = 7) -> list:
        """Compress daily files older than *days*."""
        mem_dir = os.path.join(self.workspace, "memory")
        return self.compression.compress_old_files(mem_dir, days)

    # ── synthesis ───────────────────────────────────────────────────────

    def synthesize(self, research_results: Dict = None) -> Dict:
        """Run autonomous knowledge synthesis cycle.
        
        Args:
            research_results: Optional dict of {source: research_info} to integrate
            
        Returns:
            Synthesis report with gaps, suggestions, and integration results
        """
        report = self.synthesis.run_cycle(self.memories, research_results)
        
        # Add any new synthesized entries to our memory store
        if research_results and "new_entries" in report:
            for entry_data in report["new_entries"]:
                entry = MemoryEntry.from_dict(entry_data)
                if entry.hash not in self._hashes:
                    self.memories.append(entry)
                    self._hashes.add(entry.hash)
        
        return report

    def research_suggestions(self, limit: int = 5) -> List[Dict]:
        """Get research topic suggestions based on knowledge gaps.
        
        Args:
            limit: Maximum number of suggestions to return
            
        Returns:
            List of research suggestions with topic, reason, and priority
        """
        return self.synthesis.suggest_research_topics(self.memories, limit)

    # ── stats ───────────────────────────────────────────────────────────

    def stats(self) -> Dict:
        now = datetime.now()
        scores = [self.decay.score(m, now) for m in self.memories]
        sentiments = defaultdict(int)
        for m in self.memories:
            dom = self.sentiment.dominant(m.sentiment)
            if dom:
                sentiments[dom] += 1
        categories = defaultdict(int)
        for m in self.memories:
            categories[m.category] += 1

        return {
            "total": len(self.memories),
            "avg_score": round(sum(scores) / max(len(scores), 1), 4),
            "archive_candidates": sum(1 for s in scores if s < self.decay.archive_threshold),
            "sentiments": dict(sentiments),
            "categories": dict(categories),
            "avg_confidence": round(
                sum(m.confidence for m in self.memories) / max(len(self.memories), 1), 4
            ),
        }

    # ── private ─────────────────────────────────────────────────────────

    def _extract_tags(self, text: str) -> List[str]:
        tags = []
        t = text.lower()
        for term in self._tag_terms:
            if term in t:
                tags.append(term)
        for m in re.findall(r"\$[\d,]+(?:\.\d{2})?", text):
            tags.append(m)
        return tags[:10]

    def _append_audit(self, entry: Dict) -> None:
        log = []
        if os.path.exists(self.audit_path):
            with open(self.audit_path) as f:
                log = json.load(f)
        log.append(entry)
        with open(self.audit_path, "w") as f:
            json.dump(log[-100:], f, indent=2)
