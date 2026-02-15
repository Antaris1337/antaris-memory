# 🧠 Antaris Memory

**Persistent memory for AI agents. Zero dependencies. Just files.**

Store, search, decay, and consolidate agent memories using only the Python standard library. No vector databases, no infrastructure, no API keys required.

[![PyPI](https://img.shields.io/pypi/v/antaris-memory)](https://pypi.org/project/antaris-memory/)
[![Tests](https://img.shields.io/badge/tests-22%20passing-brightgreen)](https://github.com/Antaris-Analytics/antaris-memory)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-orange.svg)](LICENSE)

## What This Is

- A **file-based memory store** for AI agents with automatic decay, sentiment tagging, and temporal indexing
- Stores structured facts, decisions, and context as JSON — searchable by keyword, date, category, or sentiment
- Retrieval is weighted by **recency × importance × access frequency** (Ebbinghaus-inspired decay)
- "Contradiction detection" means: flag when two stored memories contain conflicting claims (keyword-based, deterministic — no LLM required)
- Runs **fully offline** with zero external dependencies

## What This Isn't

- **Not a vector database** — no embeddings by default (optional in a future release)
- **Not a knowledge graph** — it's a flat memory store with metadata
- **Not magic** — memory quality depends on what you feed it
- **Not LLM-dependent** — everything is deterministic keyword/pattern matching. Zero API calls, zero tokens
- **Will not detect semantic contradictions phrased differently** — contradiction detection compares normalized statements and flags conflicts when mutually exclusive assertions share the same subject. It's rule-based, not semantic
- **No network calls** — runs fully offline, never phones home

## The Problem

Every AI agent forgets everything between sessions. The typical solutions — Mem0, Zep, LangChain Memory — require database infrastructure to deploy. Sometimes you just want persistent memory that works with `pip install` and a folder.

## The Solution

```python
from antaris_memory import MemorySystem

# Initialize
mem = MemorySystem("./my-agent-workspace")

# Ingest conversations, notes, anything
mem.ingest_file("conversation.md", category="tactical")
mem.ingest_directory("./memory", pattern="*.md", category="tactical")

# Search with decay-weighted relevance
results = mem.search("what did we decide about pricing?")

# Ask about time
memories = mem.on_date("2026-02-14")
story = mem.narrative(topic="database migration")

# Forget things (GDPR-ready)
mem.forget(entity="John Doe")
mem.forget(before_date="2025-01-01")

# Run dream-state consolidation
report = mem.consolidate()

# Save
mem.save()
```

## Features

| Feature | Description |
|---------|-------------|
| **Input Gating (P0-P3)** | Classify and route information at intake — critical, operational, contextual, or ephemeral — so low-value data never enters storage |
| **Autonomous Knowledge Synthesis** | Agent independently researches and integrates new knowledge during idle periods |
| **Zero Infrastructure** | No databases, no vector stores, no cloud services. Just files. |
| **Memory Decay** | Ebbinghaus-inspired forgetting curves with reinforcement on access |
| **Sentiment Tagging** | Auto-detect emotional context (positive, negative, urgent, strategic, financial) |
| **Temporal Reasoning** | Query by date, date ranges, build chronological narratives |
| **Confidence Scoring** | Track reliability, increase on corroboration |
| **Contradiction Detection** | Flag when memories conflict with each other |
| **Memory Compression** | Auto-summarize old files, preserve key points |
| **Selective Forgetting** | GDPR-ready deletion by topic, entity, or date with audit trail |
| **Dream State** | Background consolidation: find duplicates, cluster topics, generate insights |

## Install

```bash
pip install antaris-memory
```

Or from source:

```bash
git clone https://github.com/Antaris-Analytics/antaris-memory.git
cd antaris-memory
pip install -e .
```

## What's New in v0.2

**🚪 Input Gating (P0-P3)**: Smart content triage automatically classifies information at intake:
- **P0 (Critical)**: Security alerts, errors, financial commitments, deadlines → strategic category
- **P1 (Operational)**: Decisions, assignments, technical choices → operational category  
- **P2 (Contextual)**: Background info, research, discussion → tactical category
- **P3 (Ephemeral)**: Greetings, "thanks", "OK", "lol" → silently filtered out

**🧠 Autonomous Knowledge Synthesis**: During idle periods, your agent now:
- Identifies knowledge gaps (unanswered questions, TODOs, unexplained terms)
- Suggests research topics based on memory analysis
- Integrates new research findings with existing knowledge
- Creates compound knowledge entries from cross-referenced information

**🔌 Integration Examples**: Ready-to-use examples for OpenClaw agents and LangChain chains.

```python
# Use intelligent gating
mem.ingest_with_gating(conversation, source="chat", context={"session": "123"})

# Get research suggestions  
suggestions = mem.research_suggestions(limit=5)

# Run autonomous synthesis
report = mem.synthesize(research_results={"topic": "new findings..."})
```

## Quick Start

```python
from antaris_memory import MemorySystem

# Create a memory system
mem = MemorySystem("./workspace", half_life=7.0)

# Load existing state (if any)
mem.load()

# Ingest some content
mem.ingest("Today we decided to use PostgreSQL for the database.", 
           source="meeting-notes", category="strategic")

mem.ingest("The API costs $500/month which is too expensive.",
           source="review", category="financial")

# Search
results = mem.search("database decision")
for r in results:
    print(f"[{r.confidence:.1f}] {r.content}")

# Check stats
print(mem.stats())

# Save state
mem.save()
```

## How It Works

### Memory Decay (Ebbinghaus Curves)

Memories naturally fade over time, just like human memory:

```
Score = Importance × 2^(-age / half_life) + reinforcement
```

- **Fresh memories** score high
- **Old unused memories** fade toward zero
- **Accessed memories** get reinforced — the more you recall something, the stronger it stays
- Memories below the archive threshold are candidates for compression

### Sentiment Analysis

Every memory is auto-tagged with emotional context:

```python
entry.sentiment = {"positive": 0.8, "financial": 0.5}
```

Search by emotion: `mem.search("budget", sentiment_filter="financial")`

### Dream State Consolidation

Run periodically (cron job, background task) to:
- Find and merge near-duplicate memories
- Discover topic clusters
- Detect contradictions
- Suggest memories for archival

```python
report = mem.consolidate()
# Returns: duplicates found, clusters, contradictions, archive suggestions
```

## Architecture

```
┌─────────────────────────────────────────────┐
│              MemorySystem                    │
│                                             │
│  ┌──────────┐ ┌───────────┐ ┌────────────┐ │
│  │  Decay   │ │ Sentiment │ │  Temporal   │ │
│  │  Engine  │ │  Tagger   │ │  Engine     │ │
│  └──────────┘ └───────────┘ └────────────┘ │
│  ┌──────────┐ ┌───────────┐ ┌────────────┐ │
│  │Confidence│ │Compression│ │ Forgetting  │ │
│  │  Engine  │ │  Engine   │ │  Engine     │ │
│  └──────────┘ └───────────┘ └────────────┘ │
│  ┌──────────────────────────────────────┐   │
│  │     Consolidation Engine             │   │
│  │     (Dream State Processing)         │   │
│  └──────────────────────────────────────┘   │
│                                             │
│  Storage: JSON file (zero dependencies)     │
└─────────────────────────────────────────────┘
```

## Configuration

```python
mem = MemorySystem(
    workspace="./workspace",    # Where to store metadata
    half_life=7.0,              # Memory decay half-life in days
    tag_terms=["custom", "terms"],  # Additional auto-tag keywords
)
```

## Zero Dependencies

Antaris Memory uses only Python standard library. No numpy, no torch, no API keys required.

**Optional:** Install `openai` for embedding-based semantic search (planned for a future release).

## Comparison

| Feature | Antaris Memory | LangChain Memory | Mem0 | Zep |
|---------|---------------|-----------------|------|-----|
| Input gating (P0-P3) | ✅ | ❌ | ❌ | ❌ |
| Autonomous knowledge synthesis | ✅ | ❌ | ❌ | ❌ |
| No database required | ✅ | ❌ | ❌ | ❌ |
| Memory decay curves | ✅ | ❌ | ❌ | ⚠️ Partial |
| Emotional tagging | ✅ | ❌ | ❌ | ✅ |
| Temporal reasoning | ✅ | ❌ | ❌ | ✅ |
| Contradiction detection | ✅ | ❌ | ❌ | ⚠️ Partial |
| Selective forgetting | ✅ | ❌ | ⚠️ Partial | ⚠️ Partial |
| No infrastructure needed | ✅ | ❌ | ❌ | ❌ |

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.

