"""
MemorySystem v0.4 — Production-ready with sharding, indexing, and migration.

Major improvements over v0.3:
- Sharded storage for better performance and scalability
- Fast search indexes (full-text, tags, dates)
- Schema migration system
- Backward compatibility with v0.2/v0.3 data

Usage:
    from antaris_memory import MemorySystem

    mem = MemorySystem("./workspace")
    mem.ingest_file("notes.md", category="tactical")
    results = mem.search("patent filing")  # Uses fast indexes
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
                print(f"✅ Migrated from {migration_result['from_version']} to {migration_result['to_version']}")
            elif migration_result["status"] == "error":
                print(f"❌ Migration failed: {migration_result['message']}")
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
        
        return "sharded format"
    
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
        return len(self.memories)
    
    def _load_legacy(self) -> int:
        """Load from v0.2/v0.3 legacy single-file format."""
        if not os.path.exists(self.legacy_metadata_path):
            return 0
        
        with open(self.legacy_metadata_path) as f:
            data = json.load(f)
        
        self.memories = [MemoryEntry.from_dict(d) for d in data.get("memories", [])]
        self._hashes = {m.hash for m in self.memories}
        return len(self.memories)

    # ── search with indexing ───────────────────────────────────────────

    def search(self, 
               query: str, 
               limit: int = 20,
               tags: Optional[List[str]] = None,
               tag_mode: str = "any",
               date_range: Optional[Tuple[str, str]] = None,
               use_decay: bool = True) -> List[MemoryEntry]:
        """Search memories using fast indexes when available."""
        
        if self.use_indexing and self.index_manager:
            return self._search_indexed(query, limit, tags, tag_mode, date_range, use_decay)
        else:
            return self._search_legacy(query, limit, use_decay)
    
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


# Backward compatibility alias
MemorySystem = MemorySystemV4