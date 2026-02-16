"""
Antaris Memory — File-based persistent memory for AI agents.

Store, search, decay, and consolidate agent memories using only the
Python standard library. Zero dependencies, deterministic operations,
transparent JSON storage.

Usage:
    from antaris_memory import MemorySystem

    mem = MemorySystem("./workspace")
    mem.load()
    mem.ingest("Key decision made", source="meeting", category="strategic")
    results = mem.search("decision")
    mem.save()
"""

__version__ = "1.0.0"

# Core
from antaris_memory.core_v4 import MemorySystemV4 as MemorySystem
from antaris_memory.entry import MemoryEntry
from antaris_memory.decay import DecayEngine
from antaris_memory.sentiment import SentimentTagger
from antaris_memory.temporal import TemporalEngine
from antaris_memory.confidence import ConfidenceEngine
from antaris_memory.compression import CompressionEngine
from antaris_memory.forgetting import ForgettingEngine
from antaris_memory.consolidation import ConsolidationEngine
from antaris_memory.gating import InputGate
from antaris_memory.synthesis import KnowledgeSynthesizer

# Multi-agent
from antaris_memory.shared import SharedMemoryPool, AgentPermission

# Storage
from antaris_memory.sharding import ShardManager, ShardKey
from antaris_memory.migration import MigrationManager, Migration
from antaris_memory.indexing import IndexManager, SearchIndex, TagIndex, DateIndex

# Concurrency
from antaris_memory.locking import FileLock, LockTimeout
from antaris_memory.versioning import VersionTracker, ConflictError

# Search
from antaris_memory.search import SearchEngine, SearchResult

# Backward compatibility - import legacy core if needed
try:
    from antaris_memory.core import MemorySystem as LegacyMemorySystem
except ImportError:
    LegacyMemorySystem = None

__all__ = [
    "MemorySystem",
    "MemoryEntry",
    
    # Core engines
    "DecayEngine",
    "SentimentTagger", 
    "TemporalEngine",
    "ConfidenceEngine",
    "CompressionEngine",
    "ForgettingEngine",
    "ConsolidationEngine",
    "InputGate",
    "KnowledgeSynthesizer",
    
    # Multi-agent (v0.3)
    "SharedMemoryPool",
    "AgentPermission",
    
    # Production features (v0.4)
    "ShardManager",
    "ShardKey", 
    "MigrationManager",
    "Migration",
    "IndexManager",
    "SearchIndex",
    "TagIndex",
    "DateIndex",
    
    # Concurrency (v0.5)
    "FileLock",
    "LockTimeout",
    "VersionTracker",
    "ConflictError",
    
    # Search (v1.0)
    "SearchEngine",
    "SearchResult",
]
