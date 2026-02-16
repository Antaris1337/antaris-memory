"""
Antaris Memory — File-based persistent memory for AI agents.


Give your AI agents persistent memory that decays, reinforces,
feels, reasons about time, and cleans up after itself.
For under $5/year.

Usage:
    from antaris_memory import MemorySystem

    mem = MemorySystem("/path/to/workspace")
    mem.ingest_file("conversation.md", category="tactical")
    results = mem.search("what did we decide about pricing?")
    mem.save()
"""

__version__ = "0.3.0"

from antaris_memory.core import MemorySystem
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
from antaris_memory.shared import SharedMemoryPool, AgentPermission

__all__ = [
    "MemorySystem",
    "MemoryEntry",
    "DecayEngine",
    "SentimentTagger",
    "TemporalEngine",
    "ConfidenceEngine",
    "CompressionEngine",
    "ForgettingEngine",
    "ConsolidationEngine",
    "InputGate",
    "KnowledgeSynthesizer",
    "SharedMemoryPool",
    "AgentPermission",
]
