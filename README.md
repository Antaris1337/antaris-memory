# Antaris Memory

**Production-ready file-based persistent memory for AI agents. Zero dependencies (core).**

Store, search, decay, and consolidate agent memories using only the Python standard library. Sharded storage for scalability, fast search indexes, automatic schema migration. No vector databases, no infrastructure, no API keys.

[![PyPI](https://img.shields.io/pypi/v/antaris-memory)](https://pypi.org/project/antaris-memory/)
[![Tests](https://github.com/Antaris-Analytics/antaris-memory/actions/workflows/tests.yml/badge.svg)](https://github.com/Antaris-Analytics/antaris-memory/actions/workflows/tests.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-orange.svg)](LICENSE)

## What's New in v1.0.0

- **BM25-inspired search** — proper relevance ranking with IDF weighting. No more wall of 0.50 scores.
- **File locking** — cross-platform `os.mkdir()`-based locks prevent concurrent writer data loss
- **Optimistic conflict detection** — mtime/hash tracking catches stale read-modify-write patterns
- **78 tests** — comprehensive coverage across search, locking, versioning, and all core features

See [CHANGELOG.md](CHANGELOG.md) for full version history.

## What It Does

- **Sharded storage** for production scalability (10,000+ memories, sub-second search)
- **Fast search indexes** (full-text, tags, dates) stored as transparent JSON files
- **Automatic schema migration** from single-file to sharded format with rollback
- **Multi-agent shared memory** pools with namespace isolation and access controls
- Retrieval weighted by **recency × importance × access frequency** ([Ebbinghaus-inspired](https://en.wikipedia.org/wiki/Forgetting_curve) decay)
- **[Input gating](#input-gating-p0p3)** classifies incoming content by priority (P0–P3) and drops ephemeral noise at intake
- Detects contradictions between stored memories using deterministic rule-based comparison
- Runs fully offline — zero network calls, zero tokens, zero API keys

## What It Doesn't Do

- **Not a vector database** — no embeddings. Search uses TF-IDF-style keyword matching on an inverted index, not semantic similarity. If you need "find memories *similar in meaning*," this isn't the right tool yet.
- **Not a knowledge graph** — flat memory store with metadata indexing. No entity relationships or graph traversal.
- **Not semantic** — contradiction detection compares normalized statements using explicit conflict rules (negation, numeric disagreement), not inference. It will not catch contradictions phrased differently.
- **Not LLM-dependent** — all operations are deterministic. No model calls, no prompt engineering.
- **Not infinitely scalable** — JSON file storage works well up to ~50,000 memories per workspace. Beyond that, you'll want a database. We're honest about this because we'd rather you succeed than discover limits in production.

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

mem.save()
```

More examples in the [`examples/`](examples/) directory:
- [`quickstart.py`](examples/quickstart.py) — basic usage
- [`openclaw_integration.py`](examples/openclaw_integration.py) — OpenClaw agent integration
- [`langchain_integration.py`](examples/langchain_integration.py) — LangChain memory backend

## Input Gating (P0–P3)

**Input gating** classifies content at intake by priority level. Low-value data (greetings, filler, acknowledgments) never enters storage, keeping memory clean without manual curation.

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

Classification uses keyword and pattern matching — no LLM calls. It's fast (0.177ms avg) but not perfect. Edge cases exist; when in doubt, it errs toward storing.

## Knowledge Synthesis

**Knowledge synthesis** identifies gaps in stored knowledge and integrates new research. It scans existing memories for topics mentioned frequently but lacking detail, then suggests targeted research.

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
- Accessed memories are automatically reinforced (each search hit boosts the score)
- Below-threshold memories are candidates for compression

## Consolidation

Run periodically to maintain memory health:

```python
report = mem.consolidate()
```

**Sample output** (10 memories, 2 near-duplicates, 3 topic clusters):

```json
{
  "timestamp": "2026-02-16T02:23:58",
  "total": 10,
  "active": 10,
  "archive_candidates": 0,
  "duplicates": 0,
  "clusters": 3,
  "contradictions": 0,
  "top_clusters": {
    "postgresql": ["4d8c1f76", "9178bfd3"],
    "cost": ["a0811e1b", "5b42672b"],
    "$500": ["a0811e1b", "5b42672b"]
  }
}
```

- Finds and merges near-duplicate memories (e.g., "Chose PostgreSQL" and "PostgreSQL selected as database")
- Discovers topic clusters (memories that reference the same subjects)
- Flags contradictions (e.g., "API costs are reasonable" vs "API costs too much" — when phrased with explicit negation)
- Suggests memories for archival (old, low-importance, rarely accessed)

## Concurrency

Multiple processes can safely read and write to the same memory workspace.

### File Locking

```python
from antaris_memory import FileLock

# Exclusive access to a resource
with FileLock("/path/to/shard.json", timeout=10.0):
    data = load(shard)
    modify(data)
    save(shard, data)

# Non-blocking try
lock = FileLock("/path/to/shard.json")
if lock.acquire(blocking=False):
    try:
        ...
    finally:
        lock.release()
```

Locks use `os.mkdir()` — atomic on all platforms, works on network filesystems, zero dependencies. Stale locks from crashed processes are automatically detected and broken (by age or dead PID).

### Optimistic Conflict Detection

For read-heavy workloads where locking overhead isn't worth it:

```python
from antaris_memory import VersionTracker

tracker = VersionTracker()

# Snapshot before reading
version = tracker.snapshot("/path/to/data.json")
data = load(data_path)
modify(data)

# Check before writing — raises ConflictError if another process modified the file
tracker.check(version)
save(data_path, data)

# Or use the retry helper:
tracker.safe_update("/path/to/data.json", lambda d: {**d, "count": d["count"] + 1})
```

### Safety Stack

All JSON writes use `atomic_write_json()` which combines:
1. **Atomic writes** (tmpfile → fsync → os.replace) — prevents torn files
2. **File locks** (os.mkdir) — prevents lost updates from concurrent writers
3. **Directory fsync** (POSIX) — crash-consistent renames

To opt out of locking for single-process workloads: `atomic_write_json(path, data, lock=False)`.

## Benchmarks

Measured on Apple M4, Python 3.14 (beta). Results on Python 3.9–3.13 will be comparable — no version-specific optimizations are used. Reproducible via [`scripts/ollama_benchmark.py`](scripts/ollama_benchmark.py).

| Memories | Ingest | Search (avg) | Search (p99) | Consolidate | Disk |
|----------|--------|-------------|-------------|-------------|------|
| 100 | 1.0ms (0.010ms/entry) | 0.35ms | 0.40ms | 2.6ms | 46KB |
| 500 | 4.4ms (0.009ms/entry) | 1.55ms | 1.83ms | 51ms | 230KB |
| 1,000 | 7.1ms (0.007ms/entry) | 2.69ms | 3.20ms | 195ms | 460KB |
| 5,000 | 36.8ms (0.007ms/entry) | 13.8ms | 16.2ms | 354ms | 2.3MB |

Input gating (P0–P3 classification): **0.177ms avg** per input.

**Scaling notes:** JSON file storage is practical up to ~50,000 memories per workspace. At that scale, expect ~50-100ms search and ~50MB on disk. Beyond that, consider sharding across multiple workspaces or migrating to a database. We chose this limit deliberately — most agent workloads generate hundreds to low thousands of memories, not millions.

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
MemorySystem (v1.0)
├── ShardManager       — Distributes memories across date/topic shards
├── IndexManager       — Full-text, tag, and date indexes for fast lookup
│   ├── SearchIndex    — Inverted index for text search
│   ├── TagIndex       — Tag → memory hash mapping
│   └── DateIndex      — Date range queries
├── MigrationManager   — Schema versioning with backup and rollback
├── SearchEngine       — BM25-inspired ranking with IDF, phrase boost, field boost
├── FileLock           — Cross-platform directory-based file locking
├── VersionTracker     — Optimistic conflict detection (mtime/hash)
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

## Works With Local Models (Ollama)

All memory operations are local and deterministic — no tokens consumed, no API calls. Pair with Ollama for a fully local agent stack at zero marginal cost.

```python
mem = MemorySystem("./workspace")
mem.load()
mem.ingest_with_gating("Meeting notes from standup", source="daily")
results = mem.search("standup decisions")
```

On a Mac Mini (32GB) running Ollama for inference and antaris-memory for persistence, your entire agent stack runs locally. On a Mac Studio (256GB), you can run 70B+ models alongside thousands of indexed memories with sub-millisecond lookups.

## Running Tests

```bash
git clone https://github.com/Antaris-Analytics/antaris-memory.git
cd antaris-memory
python -m pytest tests/ -v
```

All 44 tests pass with zero external dependencies. No test fixtures, no mocking libraries, no network access.

## Zero Dependencies (Core)

The core package uses only the Python standard library — no install-time dependencies. Optional extras (`pip install antaris-memory[embeddings]`) add integration points but are never required. All core operations (ingest, search, decay, consolidation) are fully deterministic with no external calls.

## Comparison

| | Antaris Memory | [LangChain Memory](https://python.langchain.com/docs/modules/memory/) | [Mem0](https://github.com/mem0ai/mem0) | [Zep](https://github.com/getzep/zep) |
|---|---|---|---|---|
| Input gating | ✅ [P0-P3](#input-gating-p0p3) | ❌ | ❌ | ❌ |
| Knowledge synthesis | ✅ [Gap detection](#knowledge-synthesis) | ❌ | ❌ | ❌ |
| No database required | ✅ | ❌ | ❌ | ❌ |
| Memory decay | ✅ [Ebbinghaus](#memory-decay) | ❌ | ❌ | ⚠️ Temporal graphs |
| Tone tagging | ✅ Rule-based keywords | ❌ | ❌ | ✅ NLP |
| Temporal queries | ✅ | ❌ | ❌ | ✅ |
| Contradiction detection | ✅ [Rule-based](#consolidation) | ❌ | ❌ | ⚠️ Fact evolution |
| Selective forgetting | ✅ With audit | ❌ | ⚠️ Invalidation | ⚠️ Invalidation |
| Infrastructure needed | None | Redis/PG | Vector + KV + Graph | PostgreSQL + Vector |

**Honest caveat:** LangChain, Mem0, and Zep offer features we don't — embeddings-based semantic search, graph relationships, real-time sync. They require more infrastructure but may be the right choice if you need those capabilities. Antaris Memory is for teams that want a simple, transparent, offline-first memory primitive.

## Part of the Antaris Analytics Suite

- **antaris-memory** — Persistent memory for AI agents (this package)
- **[antaris-router](https://pypi.org/project/antaris-router/)** — Adaptive model routing with outcome learning
- **antaris-guard** — Security and prompt injection detection (coming soon)
- **antaris-context** — Context window optimization (coming soon)

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
