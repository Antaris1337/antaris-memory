"""
MemorySystem — Production-ready memory system with sharding, BM25 search, and concurrency safety.

Features:
- Sharded storage for scalability (10K+ memories)
- BM25-inspired search with IDF weighting and field boosting
- File locking and optimistic conflict detection
- Fast indexes (full-text, tags, dates)
- Schema migration with backward compatibility

Usage:
    from antaris_memory import MemorySystem

    mem = MemorySystem("./workspace")
    mem.load()
    mem.ingest("Key decision", source="meeting", category="strategic")
    results = mem.search("decision")
    mem.save()  # Saves to sharded format
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
from .sharding import ShardManager
from .migration import MigrationManager
from .indexing import IndexManager
from .search import SearchEngine, SearchResult

# Default tags to auto-extract
_DEFAULT_TAG_TERMS = [
    "web3", "ethereum", "postgresql", "optimization", "cost",
    "revenue", "security", "deployment", "production", "testing",
]


class MemorySystemV4:
    """Production-ready memory system with sharding and indexing.

    Parameters
    ----------
    workspace : str
        Root directory. Shards and indexes are stored here.
    half_life : float
        Decay half-life in days (default 7).
    tag_terms : list[str] | None
        Custom terms to auto-tag. Merged with built-in defaults.
    use_sharding : bool
        Whether to use sharded storage (default True for v0.4).
    use_indexing : bool
        Whether to build search indexes (default True for v0.4).
    """

    def __init__(
        self,
        workspace: str = ".",
        half_life: float = 7.0,
        tag_terms: List[str] = None,
        use_sharding: bool = True,
        use_indexing: bool = True,
    ):
        self.workspace = os.path.abspath(workspace)
        self.use_sharding = use_sharding
        self.use_indexing = use_indexing
        
        # Backward compatibility paths
        self.legacy_metadata_path = os.path.join(self.workspace, "memory_metadata.json")
        self.audit_path = os.path.join(self.workspace, "memory_audit.json")

        # v0.4 managers
        self.migration_manager = MigrationManager(workspace)
        self.shard_manager = ShardManager(workspace) if use_sharding else None
        self.index_manager = IndexManager(workspace) if use_indexing else None

        # Engines (same as v0.3)
        self.decay = DecayEngine(half_life=half_life)
        self.sentiment = SentimentTagger()
        self.temporal = TemporalEngine()
        self.confidence = ConfidenceEngine()
        self.compression = CompressionEngine()
        self.forgetting = ForgettingEngine()
        self.consolidation = ConsolidationEngine(decay=self.decay)
        self.gating = InputGate()
        self.synthesis = KnowledgeSynthesizer()
        self.search_engine = SearchEngine()

        # Tag terms
        self._tag_terms = list(set(_DEFAULT_TAG_TERMS + (tag_terms or [])))

        # Memory store (in-memory cache)
        self.memories: List[MemoryEntry] = []
        self._hashes: set = set()
        
        # Initialize system
        self._initialize()

    def _initialize(self):
        """Initialize the memory system, handling migrations if needed."""
        # Check if migration is needed
        if self.migration_manager.needs_migration():
            migration_result = self.migration_manager.migrate()
            if migration_result["status"] == "success":
                import logging
                logging.getLogger("antaris_memory").info(
                    f"Migrated from {migration_result['from_version']} to {migration_result['to_version']}")
            elif migration_result["status"] == "error":
                logging.getLogger("antaris_memory").error(
                    f"Migration failed: {migration_result['message']}")
                # Fall back to legacy format
                self.use_sharding = False
                self.use_indexing = False
        
        # Load existing data
        self.load()

    # ── persistence ─────────────────────────────────────────────────────

    def save(self) -> str:
        """Save memory state to disk using the appropriate format."""
        if self.use_sharding and self.shard_manager:
            return self._save_sharded()
        else:
            return self._save_legacy()
    
    def _save_sharded(self) -> str:
        """Save using v0.4 sharded format."""
        if not self.shard_manager:
            return self._save_legacy()
        
        # Group memories by shard
        shard_groups = self.shard_manager.shard_memories(self.memories)
        
        # Save each shard
        for shard_key, shard_memories in shard_groups.items():
            self.shard_manager.save_shard(shard_key, shard_memories)
            self.shard_manager.index.add_shard(shard_key, shard_memories)
        
        # Save shard index
        self.shard_manager.index.save_index()
        
        # Update search indexes
        if self.use_indexing and self.index_manager:
            self.index_manager.rebuild_indexes(self.memories)
            self.index_manager.save_all_indexes()
        
        shard_dir = os.path.join(self.workspace, "shards")
        return shard_dir
    
    def _save_legacy(self) -> str:
        """Save using v0.2/v0.3 legacy single-file format."""
        data = {
            "version": "0.4.0",
            "saved_at": datetime.now().isoformat(),
            "count": len(self.memories),
            "format": "legacy",
            "memories": [m.to_dict() for m in self.memories],
        }
        with open(self.legacy_metadata_path, "w") as f:
            json.dump(data, f, indent=2)
        return self.legacy_metadata_path

    def load(self) -> int:
        """Load memory state from disk, auto-detecting format."""
        if self.use_sharding and self.shard_manager:
            count = self._load_sharded()
            if count > 0:
                return count
        
        # Fall back to legacy format
        return self._load_legacy()
    
    def _load_sharded(self) -> int:
        """Load from v0.4 sharded format."""
        if not self.shard_manager:
            return 0
        
        # Load all memories from shards (careful with memory usage)
        self.memories = self.shard_manager.get_all_memories(limit=10000)  # Limit for safety
        self._hashes = {m.hash for m in self.memories}
        if self.memories:
            self.search_engine.build_index(self.memories)
        return len(self.memories)
    
    def _load_legacy(self) -> int:
        """Load from v0.2/v0.3 legacy single-file format."""
        if not os.path.exists(self.legacy_metadata_path):
            return 0
        
        with open(self.legacy_metadata_path) as f:
            data = json.load(f)
        
        self.memories = [MemoryEntry.from_dict(d) for d in data.get("memories", [])]
        self._hashes = {m.hash for m in self.memories}
        if self.memories:
            self.search_engine.build_index(self.memories)
        return len(self.memories)

    # ── search with indexing ───────────────────────────────────────────

    def search(self, 
               query: str, 
               limit: int = 20,
               tags: Optional[List[str]] = None,
               tag_mode: str = "any",
               date_range: Optional[Tuple[str, str]] = None,
               use_decay: bool = True,
               category: str = None,
               min_confidence: float = 0.0,
               sentiment_filter: str = None,
               explain: bool = False) -> list:
        """Search memories using BM25-inspired ranking with optional fast indexes.
        
        v1.0: Uses BM25 scoring with IDF weighting for proper relevance ranking.
        Backward-compatible with all v0.3/v0.4 parameters.
        
        Args:
            explain: If True, return SearchResult objects with score explanations.
        """
        # Filter by sentiment first
        memories = self.memories
        if sentiment_filter:
            memories = [m for m in memories if hasattr(m, 'sentiment') and m.sentiment and sentiment_filter in m.sentiment]
        
        # Build search index if not yet built
        if self.search_engine._doc_count != len(memories):
            self.search_engine.build_index(memories)
        
        # Use BM25 search engine
        decay_fn = self.decay.score if use_decay else None
        search_results = self.search_engine.search(
            query=query,
            memories=memories,
            limit=limit,
            category=category,
            min_score=min_confidence,
            decay_fn=decay_fn,
        )
        
        # Reinforce accessed memories
        for r in search_results:
            self.decay.reinforce(r.entry)
        
        if explain:
            return search_results
        
        # Backward compat: return MemoryEntry with updated confidence
        entries = []
        for r in search_results:
            r.entry.confidence = r.relevance
            entries.append(r.entry)
        return entries
    
    def _search_indexed(self, 
                       query: str,
                       limit: int,
                       tags: Optional[List[str]],
                       tag_mode: str,
                       date_range: Optional[Tuple[str, str]],
                       use_decay: bool) -> List[MemoryEntry]:
        """Fast search using indexes."""
        
        # Get results from indexes
        indexed_results = self.index_manager.search(
            query=query,
            tags=tags,
            tag_mode=tag_mode,
            date_range=date_range,
            limit=limit * 2  # Get more for decay scoring
        )
        
        if not indexed_results:
            return []
        
        # Convert hash results to memory objects
        hash_to_memory = {m.hash: m for m in self.memories}
        results = []
        
        for memory_hash, base_score in indexed_results:
            if memory_hash in hash_to_memory:
                memory = hash_to_memory[memory_hash]
                
                # Apply decay scoring if requested
                if use_decay:
                    decay_score = self.decay.score(memory)
                    final_score = base_score * (0.5 + decay_score)
                    # Reinforce memory (simulate access)
                    self.decay.reinforce(memory)
                else:
                    final_score = base_score
                
                results.append((memory, final_score))
        
        # Sort by final score and return
        results.sort(key=lambda x: x[1], reverse=True)
        return [memory for memory, score in results[:limit]]
    
    def _search_legacy(self, query: str, limit: int, use_decay: bool) -> List[MemoryEntry]:
        """Fallback to legacy search method."""
        import re
        
        query_lower = query.lower()
        results = []
        
        for memory in self.memories:
            content_lower = memory.content.lower()
            
            # Simple text matching
            if query_lower in content_lower:
                if use_decay:
                    decay_score = self.decay.score(memory)
                    self.decay.reinforce(memory)
                    score = decay_score
                else:
                    score = 1.0
                
                results.append((memory, score))
        
        # Sort by score
        results.sort(key=lambda x: x[1], reverse=True)
        return [memory for memory, score in results[:limit]]

    # ── ingestion ───────────────────────────────────────────────────────

    def ingest(self, content: str, source: str = "inline",
               category: str = "general") -> int:
        """Ingest raw text. Returns count of new memories added."""
        count = 0
        for i, line in enumerate(content.split("\\n")):
            stripped = line.strip()
            if len(stripped) < 15 or stripped.startswith("```") or stripped == "---":
                continue
            
            entry = MemoryEntry(stripped, source, i + 1, category)
            if entry.hash in self._hashes:
                continue
            
            # Process through gating system
            gate_priority = self.gating.classify(stripped)
            if gate_priority == "P3":  # Skip noise
                continue
            
            entry.tags = self._extract_tags(stripped)
            entry.sentiment = self.sentiment.analyze(stripped)
            # Confidence starts at default 0.5, can be adjusted later
            
            self.memories.append(entry)
            self._hashes.add(entry.hash)
            
            # Add to indexes if enabled
            if self.use_indexing and self.index_manager:
                self.index_manager.add_memory(entry)
            
            count += 1
        
        return count

    def ingest_file(self, file_path: str, category: str = "tactical") -> int:
        """Ingest a single file."""
        if not os.path.exists(file_path):
            return 0
        
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            return self.ingest(content, source=file_path, category=category)
        except (OSError, UnicodeDecodeError):
            return 0

    def ingest_directory(self, dir_path: str, category: str = "tactical",
                        pattern: str = "*.md") -> int:
        """Ingest all matching files in a directory."""
        if not os.path.exists(dir_path):
            return 0
        
        total = 0
        for path in Path(dir_path).glob(pattern):
            if path.is_file():
                total += self.ingest_file(str(path), category)
        return total

    # ── analysis & synthesis ────────────────────────────────────────────

    def analyze(self, query: str, limit: int = 10) -> Dict:
        """Analyze memories related to a query."""
        memories = self.search(query, limit=limit)
        if not memories:
            return {"status": "no_results", "query": query}
        
        # Basic analysis (can be enhanced)
        categories = defaultdict(int)
        sentiment_scores = []
        date_range = []
        
        for memory in memories:
            if memory.category:
                categories[memory.category] += 1
            if memory.sentiment and 'compound' in memory.sentiment:
                sentiment_scores.append(memory.sentiment['compound'])
            date_range.append(memory.created[:10])
        
        return {
            "status": "success",
            "query": query,
            "total_memories": len(memories),
            "categories": dict(categories),
            "avg_sentiment": sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0,
            "date_range": [min(date_range), max(date_range)] if date_range else [],
            "sample_memories": [m.content[:100] for m in memories[:3]]
        }

    def synthesize_knowledge(self, topic: str, limit: int = 20) -> Optional[str]:
        """Generate knowledge synthesis using the KnowledgeSynthesizer."""
        memories = self.search(topic, limit=limit)
        if not memories:
            return None
        
        memory_texts = [m.content for m in memories]
        return self.synthesis.synthesize(memory_texts, topic)

    # ── utility methods ─────────────────────────────────────────────────

    def _extract_tags(self, content: str) -> List[str]:
        """Extract tags from content."""
        tags = []
        content_lower = content.lower()
        
        # Extract explicit tags (@tag format)
        explicit_tags = re.findall(r'@([a-zA-Z][a-zA-Z0-9_-]*)', content)
        tags.extend(explicit_tags)
        
        # Auto-tag based on terms
        for term in self._tag_terms:
            if term.lower() in content_lower:
                tags.append(term)
        
        return list(set(tags))  # Remove duplicates

    def compact(self) -> Dict:
        """Compact memory storage by removing duplicates and merging similar entries."""
        original_count = len(self.memories)
        
        # Remove exact duplicates (by hash)
        seen_hashes = set()
        unique_memories = []
        
        for memory in self.memories:
            if memory.hash not in seen_hashes:
                unique_memories.append(memory)
                seen_hashes.add(memory.hash)
        
        # Apply forgetting engine
        retained_memories = self.forgetting.apply_forgetting(unique_memories)
        
        # Apply consolidation
        consolidated_memories = self.consolidation.consolidate_memories(retained_memories)
        
        self.memories = consolidated_memories
        self._hashes = {m.hash for m in self.memories}
        
        # Rebuild indexes after compaction
        if self.use_indexing and self.index_manager:
            self.index_manager.rebuild_indexes(self.memories)
        
        return {
            "original_count": original_count,
            "final_count": len(self.memories),
            "removed_count": original_count - len(self.memories)
        }

    # ── system management ───────────────────────────────────────────────

    def get_stats(self) -> Dict:
        """Get comprehensive system statistics."""
        stats = {
            "version": "0.4.0",
            "total_memories": len(self.memories),
            "workspace": self.workspace,
            "features": {
                "sharding": self.use_sharding,
                "indexing": self.use_indexing
            }
        }
        
        if self.use_sharding and self.shard_manager:
            stats["sharding"] = self.shard_manager.index.get_stats()
        
        if self.use_indexing and self.index_manager:
            stats["indexing"] = self.index_manager.get_combined_stats()
        
        # Memory distribution by category
        categories = defaultdict(int)
        for memory in self.memories:
            categories[memory.category or "uncategorized"] += 1
        stats["categories"] = dict(categories)
        
        return stats

    def migrate_to_v4(self) -> Dict:
        """Manually trigger migration to v0.4 format."""
        return self.migration_manager.migrate("0.4.0")
    
    def rollback_migration(self) -> Dict:
        """Rollback the most recent migration."""
        return self.migration_manager.rollback()
    
    def validate_data(self) -> Dict:
        """Validate the current data schema."""
        return self.migration_manager.validate_schema()
    
    def rebuild_indexes(self):
        """Rebuild all search indexes from current memories."""
        if self.use_indexing and self.index_manager:
            self.index_manager.rebuild_indexes(self.memories)
            self.index_manager.save_all_indexes()
    
    def get_migration_history(self) -> List[Dict]:
        """Get history of applied migrations."""
        return self.migration_manager.get_migration_history()

    # ── Backward-compatible methods from v0.3 ──────────────────────

    def stats(self) -> Dict:
        """v0.3-compatible stats method. Adds backward-compat keys."""
        s = self.get_stats()
        now = datetime.now()
        scores = [self.decay.score(m, now) for m in self.memories]
        sentiments = defaultdict(int)
        for m in self.memories:
            dom = self.sentiment.dominant(m.sentiment)
            if dom:
                sentiments[dom] += 1
        s["total"] = len(self.memories)
        s["avg_score"] = round(sum(scores) / max(len(scores), 1), 4)
        s["archive_candidates"] = sum(1 for sc in scores if sc < self.decay.archive_threshold)
        s["sentiments"] = dict(sentiments)
        s["avg_confidence"] = round(
            sum(m.confidence for m in self.memories) / max(len(self.memories), 1), 4
        )
        return s

    def ingest_with_gating(self, content: str, source: str = "inline",
                           context: Dict = None) -> int:
        """Ingest with P0-P3 input classification. P3 content is dropped.
        
        Multi-line content is split and each line classified independently.
        """
        count = 0
        for i, line in enumerate(content.split("\n")):
            stripped = line.strip()
            if len(stripped) < 5:
                continue
            gate_context = context or {}
            gate_context.update({"source": source, "line": i + 1})
            routing = self.gating.route(stripped, gate_context)
            if not routing["store"]:
                continue
            category = routing.get("category", "tactical")
            count += self.ingest(stripped, source=source, category=category)
        return count

    def on_date(self, date: str) -> List[MemoryEntry]:
        """Get memories from a specific date."""
        return self.temporal.on_date(self.memories, date)

    def between(self, start: str, end: str) -> List[MemoryEntry]:
        """Get memories between two dates."""
        return self.temporal.between(self.memories, start, end)

    def narrative(self, topic: str = None) -> str:
        """Build a narrative from memories, optionally filtered by topic."""
        return self.temporal.narrative(self.memories, topic=topic)

    def forget(self, topic: str = None, entity: str = None,
               before_date: str = None) -> Dict:
        """Selectively forget memories with audit trail."""
        result = self.forgetting.forget(
            self.memories, topic=topic, entity=entity, before_date=before_date
        )
        if "removed" in result:
            removed_set = set(m.hash for m in result["removed"])
            self.memories = [m for m in self.memories if m.hash not in removed_set]
            # Log to audit
            for m in result["removed"]:
                self._append_audit({"action": "forget", "hash": m.hash,
                                    "content_preview": m.content[:50],
                                    "timestamp": datetime.now().isoformat()})
        return result

    def consolidate(self) -> Dict:
        """Run consolidation: dedup, clustering, contradiction detection."""
        return self.consolidation.run(self.memories)

    def compress_old(self, days: int = 7) -> list:
        """Compress memories older than N days."""
        return self.compression.compress(self.memories, days=days)

    def synthesize(self, research_results: Dict = None) -> Dict:
        """Integrate research findings into memory."""
        report = self.synthesis.run_cycle(self.memories, research_results=research_results)
        # Add synthesized entries to memory store
        if report.get("synthesized_entries", 0) > 0 and "new_entries" in report:
            for entry_dict in report["new_entries"]:
                entry = MemoryEntry.from_dict(entry_dict)
                if "synthesis" not in entry.tags:
                    entry.tags.append("synthesis")
                self.memories.append(entry)
                if self.use_indexing and self.index_manager:
                    self.index_manager.add_memory(entry)
        return report

    def research_suggestions(self, limit: int = 5) -> List[Dict]:
        """Get suggestions for knowledge gaps."""
        return self.synthesis.suggest_research_topics(self.memories, limit=limit)

    def _append_audit(self, entry: Dict) -> None:
        """Append an entry to the audit log."""
        audit = []
        if os.path.exists(self.audit_path):
            with open(self.audit_path) as f:
                audit = json.load(f)
        audit.append(entry)
        with open(self.audit_path, "w") as f:
            json.dump(audit, f, indent=2)


# Backward compatibility alias
MemorySystem = MemorySystemV4