"""
Antaris Memory — Production-ready file-based persistent memory for AI agents.

v0.4 Features:
- Sharded storage for better performance and scalability  
- Fast search indexes (full-text, tags, dates)
- Schema migration system with backward compatibility
- Multi-agent shared memory pools with access controls

Give your AI agents persistent memory that decays, reinforces,
feels, reasons about time, and scales to production workloads.
For under $5/year.

Usage:
    from antaris_memory import MemorySystem

    mem = MemorySystem("/path/to/workspace")
    mem.ingest_file("conversation.md", category="tactical")
    results = mem.search("what did we decide about pricing?")  # Uses fast indexes
    mem.save()  # Saves to sharded format

    # Multi-agent usage
    from antaris_memory import SharedMemoryPool
    
    pool = SharedMemoryPool("/shared/workspace", "team_alpha")
    pool.register_agent("agent_1", role="write")
    pool.write("agent_1", "Key insight discovered", namespace="research")
"""

__version__ = "0.4.0"

# Import v0.4 system by default
from antaris_memory.core_v4 import MemorySystemV4 as MemorySystem
from antaris_memory.entry import MemoryEntry

# Core engines (unchanged from v0.3)
from antaris_memory.decay import DecayEngine
from antaris_memory.sentiment import SentimentTagger
from antaris_memory.temporal import TemporalEngine
from antaris_memory.confidence import ConfidenceEngine
from antaris_memory.compression import CompressionEngine
from antaris_memory.forgetting import ForgettingEngine
from antaris_memory.consolidation import ConsolidationEngine
from antaris_memory.gating import InputGate
from antaris_memory.synthesis import KnowledgeSynthesizer

# Multi-agent system (v0.3 feature)
from antaris_memory.shared import SharedMemoryPool, AgentPermission

# New v0.4 systems
from antaris_memory.sharding import ShardManager, ShardKey
from antaris_memory.migration import MigrationManager, Migration
from antaris_memory.indexing import IndexManager, SearchIndex, TagIndex, DateIndex

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
]
