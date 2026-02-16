# Antaris Memory

**Production-ready file-based persistent memory for AI agents. Zero dependencies.**

Store, search, decay, and consolidate agent memories using only the Python standard library. Sharded storage for scalability, fast search indexes, automatic schema migration. No vector databases, no infrastructure, no API keys.

[![PyPI](https://img.shields.io/pypi/v/antaris-memory)](https://pypi.org/project/antaris-memory/)
[![Tests](https://img.shields.io/badge/tests-44%20passing-brightgreen)](https://github.com/Antaris-Analytics/antaris-memory)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-orange.svg)](LICENSE)

## What It Does

- **Sharded storage** for production scalability (10,000+ memories, sub-second search)
- **Fast search indexes** (full-text, tags, dates) stored as transparent JSON files
- **Automatic schema migration** from single-file to sharded format with rollback
- **Multi-agent shared memory** pools with namespace isolation and access controls
- Retrieval weighted by **recency × importance × access frequency** ([Ebbinghaus-inspired](https://en.wikipedia.org/wiki/Forgetting_curve) decay)
- Classifies incoming information by priority (P0–P3) and drops ephemeral content at intake
- Detects contradictions between stored memories using deterministic rule-based comparison
- Runs fully offline — zero network calls, zero tokens, zero API keys

## v0.4 Performance

**Single-file format (v0.2/v0.3)**:
- Search: 50-500ms for 1,000 memories (scans all)
- Storage: Single JSON file, memory usage scales linearly

**Sharded format (v0.4)**:
- Search: 1-10ms for 10,000 memories (index lookup)
- Storage: Multiple shards by date/topic, constant memory usage
- Migration: Automatic on first load with backup and rollback

## What It Doesn't Do

- **Not a vector database** — no embeddings (optional embedding support planned)
- **Not a knowledge graph** — flat memory store with metadata indexing
- **Not semantic** — contradiction detection compares normalized statements using explicit conflict rules, not inference. It will not catch contradictions phrased differently.
- **Not LLM-dependent** — all operations are deterministic. No model calls, no prompt engineering.

## Design Goals

| Goal | Rationale |
|------|-----------|
| Deterministic | Same input → same output. No model variance. |
| Offline | No network, no API keys, no phoning home. |
| Minimal surface area | One class (`MemorySystem`), obvious method names. |
| No hidden processes | Consolidation and synthesis run only when called. |
| Transparent storage | Plain JSON files. Inspect with any text editor. |

## Install

```bash
pip install antaris-memory
```

## Quick Start

```python
from antaris_memory import MemorySystem

mem = MemorySystem("./workspace", half_life=7.0)
mem.load()  # Load existing state (no-op if first run)

# Store memories
mem.ingest("Decided to use PostgreSQL for the database.",
           source="meeting-notes", category="strategic")
mem.ingest("The API costs $500/month — too expensive.",
           source="review", category="operational")

# Search (results ranked by relevance × decay score)
for r in mem.search("database decision"):
    print(f"[{r.confidence:.1f}] {r.content}")

# Temporal queries
mem.on_date("2026-02-14")
mem.narrative(topic="database migration")

# Selective deletion
mem.forget(entity="John Doe")       # GDPR-ready, with audit trail
mem.forget(before_date="2025-01-01")

# Background consolidation
report = mem.consolidate()
# → duplicates found, topic clusters, contradictions, archive suggestions

mem.save()
```

## Input Gating (P0–P3)

Classify content at intake. Low-value data never enters storage.

```python
mem.ingest_with_gating("CRITICAL: API key compromised", source="alerts")
# → P0 (critical) → stored in strategic tier

mem.ingest_with_gating("Decided to switch to PostgreSQL", source="meeting")
# → P1 (operational) → stored in operational tier

mem.ingest_with_gating("thanks for the update!", source="chat")
# → P3 (ephemeral) → dropped, not stored
```

| Level | Category | Stored | Examples |
|-------|----------|--------|----------|
| P0 | Strategic | ✅ | Security alerts, errors, deadlines, financial commitments |
| P1 | Operational | ✅ | Decisions, assignments, technical choices |
| P2 | Tactical | ✅ | Background info, research, general discussion |
| P3 | — | ❌ | Greetings, acknowledgments, filler |

## Knowledge Synthesis

Identify gaps in stored knowledge and integrate new research.

```python
# What does the agent not know enough about?
suggestions = mem.research_suggestions(limit=5)
# → [{"topic": "token optimization", "reason": "mentioned 3x, no details", "priority": "P1"}, ...]

# Integrate external findings
report = mem.synthesize(research_results={
    "token optimization": "Context window management techniques..."
})
```

## Memory Decay

Memories fade over time unless reinforced by access:

```
score = importance × 2^(-age / half_life) + reinforcement
```

- Fresh memories score high
- Unused memories decay toward zero
- Accessed memories are automatically reinforced
- Below-threshold memories are candidates for compression

## Consolidation

Run periodically to maintain memory health:

```python
report = mem.consolidate()
```

- Finds and merges near-duplicate memories
- Discovers topic clusters
- Flags contradictions (deterministic, rule-based)
- Suggests memories for archival

## Storage Format

**v0.4 (sharded)** — memories are split across multiple files by date and topic:

```
workspace/
├── shards/
│   ├── 2026-02-strategic.json    # Strategic memories from Feb 2026
│   ├── 2026-02-operational.json  # Operational memories from Feb 2026
│   └── 2026-01-tactical.json     # Tactical memories from Jan 2026
├── indexes/
│   ├── search_index.json         # Full-text inverted index
│   ├── tag_index.json            # Tag → memory hash lookup
│   └── date_index.json           # Date range index
├── migrations/
│   └── history.json              # Applied migration log
└── memory_audit.json             # Deletion audit trail (GDPR)
```

Each shard is a plain JSON file containing an array of memory entries:

```json
{
  "hash": "a1b2c3d4e5f6",
  "content": "Decided to use PostgreSQL",
  "source": "meeting-notes",
  "category": "strategic",
  "created": "2026-02-15T10:00:00",
  "importance": 1.0,
  "confidence": 0.8,
  "sentiment": {"strategic": 0.6},
  "tags": ["postgresql", "deployment"]
}
```

**v0.2/v0.3 (legacy)** — single `memory_metadata.json` file. Automatically migrated to sharded format on first v0.4 load, with backup and rollback support.

Storage format may evolve between versions. Breaking changes will increment MAJOR version. See [CHANGELOG](CHANGELOG.md).

## Architecture

```
MemorySystem (v0.4)
├── ShardManager       — Distributes memories across date/topic shards
├── IndexManager       — Full-text, tag, and date indexes for fast lookup
│   ├── SearchIndex    — Inverted index for text search
│   ├── TagIndex       — Tag → memory hash mapping
│   └── DateIndex      — Date range queries
├── MigrationManager   — Schema versioning with backup and rollback
├── InputGate          — P0-P3 classification at intake
├── DecayEngine        — Ebbinghaus forgetting curves
├── SentimentTagger    — Rule-based keyword tone tagging
├── TemporalEngine     — Date queries and narrative building
├── ConfidenceEngine   — Reliability scoring
├── CompressionEngine  — Old file summarization
├── ForgettingEngine   — Selective deletion with audit
├── ConsolidationEngine — Dedup, clustering, contradiction detection
└── KnowledgeSynthesizer — Gap identification and research integration
```

**Data flow:** `ingest → classify (P0-P3) → normalize → shard-route → index → persist → search (index lookup) → decay-weight → return`

## Zero Dependencies

The core package uses only the Python standard library. Optional integrations (LLMs, embeddings) are deliberately excluded to preserve deterministic behavior and eliminate runtime requirements.

## Comparison

| | Antaris Memory | LangChain Memory | Mem0 | Zep |
|---|---|---|---|---|
| Input gating | ✅ P0-P3 | ❌ | ❌ | ❌ |
| Knowledge synthesis | ✅ | ❌ | ❌ | ❌ |
| No database required | ✅ | ❌ | ❌ | ❌ |
| Memory decay | ✅ Ebbinghaus | ❌ | ❌ | ⚠️ Temporal graphs |
| Tone tagging | ✅ Rule-based keywords | ❌ | ❌ | ✅ NLP |
| Temporal queries | ✅ | ❌ | ❌ | ✅ |
| Contradiction detection | ✅ Rule-based | ❌ | ❌ | ⚠️ Fact evolution |
| Selective forgetting | ✅ With audit | ❌ | ⚠️ Invalidation | ⚠️ Invalidation |
| Infrastructure needed | None | Redis/PG | Vector + KV + Graph | PostgreSQL + Vector |

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
