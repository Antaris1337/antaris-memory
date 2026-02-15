"""
Antaris Memory — Human-like memory for AI agents.
Patent Pending: US Application #63/983,397

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

__version__ = "0.1.0"
__patent__ = "US Application #63/983,397 (Patent Pending)"

from antaris_memory.core import MemorySystem
from antaris_memory.entry import MemoryEntry
from antaris_memory.decay import DecayEngine
from antaris_memory.sentiment import SentimentTagger
from antaris_memory.temporal import TemporalEngine
from antaris_memory.confidence import ConfidenceEngine
from antaris_memory.compression import CompressionEngine
from antaris_memory.forgetting import ForgettingEngine
from antaris_memory.consolidation import ConsolidationEngine

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
]
