# antaris-memory

**Production-ready file-based persistent memory for AI agents. Zero dependencies (core).**

Store, search, decay, and consolidate agent memories using only the Python standard library. Sharded storage for scalability, fast search indexes, namespace isolation, memory types, retrieval feedback loops, MCP server support, and automatic schema migration. No vector databases, no infrastructure, no API keys.

[![PyPI](https://img.shields.io/pypi/v/antaris-memory)](https://pypi.org/project/antaris-memory/)
[![Tests](https://github.com/Antaris-Analytics/antaris-memory/actions/workflows/tests.yml/badge.svg)](https://github.com/Antaris-Analytics/antaris-memory/actions/workflows/tests.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-orange.svg)](LICENSE)

---

## Install

```bash
pip install antaris-memory
```

---

## Quick Start

```python
from antaris_memory import MemorySystem

mem = MemorySystem("./workspace", half_life=7.0)
mem.load()  # No-op on first run; auto-migrates old formats

# Store memories
mem.ingest("Decided to use PostgreSQL for the database.",
           source="meeting-notes", category="strategic")

# Typed helpers
mem.ingest_fact("PostgreSQL supports JSON natively")
mem.ingest_preference("User prefers concise explanations")
mem.ingest_mistake("Forgot to close DB connections in worker threads",
                   correction="Use context managers for all DB connections",
                   root_cause="Manual connection management in worker pool")
mem.ingest_procedure("Deploy: push to main, CI runs, auto-deploy to staging")

# Input gating — drops ephemeral noise (P3) before storage
mem.ingest_with_gating("Decided to switch to Redis for caching", source="chat")
mem.ingest_with_gating("thanks for the update!", source="chat")  # dropped (P3)

# Search (BM25; hybrid BM25+cosine if embedding fn set)
for r in mem.search("database decision"):
    print(f"[{r.confidence:.2f}] {r.content}")

# Save
mem.save()
```

---

## Namespaces

Every `MemorySystem` instance doubles as a namespace manager. Call `mem.namespace("name")` to get a fully isolated memory proxy — search in one namespace never returns results from another.

```python
from antaris_memory import MemorySystem

mem = MemorySystem("./workspace")

# Create and use isolated namespaces
alpha = mem.namespace("project-alpha")
alpha.ingest("Alpha uses PostgreSQL for the primary database", source="infra")
alpha.ingest_fact("Alpha API runs on port 8080")

beta = mem.namespace("project-beta")
beta.ingest("Beta uses SQLite for local storage", source="infra")

# Search is scoped — alpha never sees beta's data
results = alpha.search("database")    # only PostgreSQL result
results = beta.search("database")     # only SQLite result

# Namespace lifecycle
mem.create_namespace("staging")
mem.archive_namespace("project-beta")
mem.delete_namespace("staging", delete_data=True)
all_ns = mem.list_namespaces()  # [{"name": "default", ...}, {"name": "project-alpha", ...}]
```

Standard key-prefix constants for multi-tenant scoping:

```python
from antaris_memory.namespace import TENANT_ID, AGENT_ID, CONVERSATION_ID

tenant_ns = mem.namespace(f"{TENANT_ID}-acme")         # "tenant-acme"
agent_ns = mem.namespace(f"{AGENT_ID}-researcher-01")   # "agent-researcher-01"
conv_ns = mem.namespace(f"{CONVERSATION_ID}-abc123")     # "conversation-abc123"
```

Each namespace has its own workspace directory, shards, indexes, and WAL — full hard isolation.

---

## Memory Types

Every memory entry has a `memory_type` field that controls decay rate, importance boost, and recall priority.

```python
# Explicit memory_type on ingest()
mem.ingest("Deploy: push to main, CI runs, auto-deploy to staging",
           memory_type="procedural")

# Typed helpers set memory_type automatically
mem.ingest_fact("PostgreSQL supports JSONB indexing")          # memory_type="fact"
mem.ingest_preference("User prefers Python examples")          # memory_type="preference"
mem.ingest_procedure("Run pytest from venv, not global pip")   # memory_type="procedure"
mem.ingest_mistake(
    what_happened="Forgot to handle connection timeout",
    correction="Add timeout=30 to all HTTP calls",
    root_cause="Default timeout is infinite in requests lib",
    severity="high",
    tags=["http", "reliability"],
)  # memory_type="mistake"

# Filter search by type
procedures = mem.search("deploy process", memory_type="procedure")
mistakes = mem.search("timeout", memory_type="mistake")
```

| Type | Use for | Decay | Importance | Recall priority |
|------|---------|-------|------------|----------------|
| `episodic` | Events, decisions, meeting notes | Normal | 1.0x | Normal |
| `fact` | Facts, concepts, general knowledge | Normal | 1.2x | High |
| `preference` | User preferences, style notes | 3x slower | 1.2x | High |
| `procedure` | How-to steps, runbooks | 3x slower | 1.3x | High |
| `mistake` | Errors to avoid, lessons learned | 10x slower | 2.0x | Highest |

---

## Retrieval Feedback Loop

Record whether retrieved memories led to good or bad outcomes. The system adapts memory importance in real time — good outcomes boost importance (x1.2), bad outcomes reduce it (x0.8).

```python
# 1. Search for relevant memories
results = mem.search("database migration strategy", explain=True)

# 2. Use results to generate a response...
ids = [r.entry.hash for r in results]

# 3. Record the outcome
mem.record_outcome(ids, "good")     # boost importance of helpful memories
mem.record_outcome(ids, "bad")      # reduce importance of unhelpful memories
mem.record_outcome(ids, "neutral")  # no change

# Router integration — log routing decisions alongside retrieval outcomes
mem.record_routing_outcome(model="claude-haiku-3-5", outcome="good")

# View aggregate stats
stats = mem.feedback_stats()
# {"total": 42, "good": 30, "bad": 5, "neutral": 7, "routing": 12, "retrieval": 30}
```

Feedback is persisted as `outcomes.jsonl` in the workspace directory and survives restarts.

---

## Bulk Ingest

`bulk_ingest()` uses O(1) deferred index rebuild — a single `rebuild_indexes()` at the end instead of one per WAL flush. Benchmarked at **12,041 items/s** with **1M entries ingested in ~86s** on Apple M4, with near-flat scaling.

```python
# List-based bulk ingest
count = mem.bulk_ingest([
    "The API gateway handles authentication for all services.",
    {"content": "Deploy using helm upgrade --install", "memory_type": "procedure"},
    {"content": "PostgreSQL is the primary database", "source": "infra-docs"},
    {"content": "Never use SELECT * in production queries", "memory_type": "mistake",
     "source": "code-review"},
])

# Context manager for existing ingest() call sites
with mem.bulk_mode():
    for line in open("corpus.txt"):
        mem.ingest(line.strip(), source="corpus")
    # Index rebuilt exactly once when the block exits

# Generator-based 1M ingest
def corpus_generator():
    for i in range(1_000_000):
        yield f"Memory entry {i} with substantive content for indexing"

mem.bulk_ingest(corpus_generator())  # all entries written to shards on disk
```

At runtime, a safety limit caps the active in-memory set to **20,000 entries** by default. A `UserWarning` is emitted when the limit is hit. Typical agent use (10K-100K active memories) keeps search latency under 5ms.

---

## Production Cleanup API

Four methods for production maintenance — bulk removal, index repair, and WAL management without manual shard surgery.

### `purge()` — Bulk removal with glob patterns

```python
# Remove all memories from a specific pipeline session
result = mem.purge(source="pipeline:pipeline_abc123")
print(f"Removed {result['removed']} memories, {result['wal_removed']} WAL entries")

# Glob pattern — remove ALL pipeline sessions at once
result = mem.purge(source="pipeline:pipeline_*")

# Remove by content substring (case-insensitive)
result = mem.purge(content_contains="context_packet")

# Custom predicate (OR logic — removes if ANY criterion matches)
result = mem.purge(
    source="openclaw:auto",
    content_contains="symlink mismatch",
)

# Always persist after purge
mem.save()
```

Return value:

```python
{
    "removed": 10,        # from in-memory set
    "wal_removed": 2,     # from WAL file
    "total": 12,
    "audit": {
        "operation": "purge",
        "count": 12,
        "sources": ["pipeline:pipeline_abc123"],
        "timestamp": "2026-02-19T..."
    }
}
```

### `rebuild_indexes()` — Repair search indexes after bulk operations

```python
result = mem.rebuild_indexes()
print(f"Indexed {result['memories']} memories, {result['words_indexed']} words")
# {"memories": 9990, "words_indexed": 5800, "tags": 24}
```

### `wal_flush()` — Force-flush WAL to shard files

```python
flushed = mem.wal_flush()
print(f"Flushed {flushed} pending WAL entries to shards")
```

### `wal_inspect()` — Health check without mutating state

```python
status = mem.wal_inspect()
# {"pending_entries": 14, "size_bytes": 8192, "sample": ["content preview 1...", ...]}
print(f"WAL pending: {status['pending_entries']} entries ({status['size_bytes']} bytes)")
```

### Typical production maintenance flow

```python
from antaris_memory import MemorySystem

mem = MemorySystem("./workspace")
mem.load()

# 1. Inspect WAL health
status = mem.wal_inspect()
if status["pending_entries"] > 100:
    print(f"WAL has {status['pending_entries']} pending — flushing...")
    mem.wal_flush()

# 2. Purge stale/unwanted data
result = mem.purge(source="pipeline:pipeline_old_session_*")
print(f"Purged {result['total']} stale entries")

# 3. Rebuild indexes after purge
index_result = mem.rebuild_indexes()
print(f"Re-indexed {index_result['memories']} memories")

# 4. Persist
mem.save()
```

---

## BM25 Search

Full-text search uses BM25 with IDF weighting and field boosting. Zero dependencies, zero API calls.

```python
# Basic search — ranked by BM25 score × decay × access frequency
results = mem.search("database migration")

# With filters
results = mem.search(
    "deploy process",
    category="strategic",
    memory_type="procedure",
    min_confidence=0.3,
    limit=10,
)

# Explain mode — returns SearchResult objects with score breakdowns
results = mem.search("authentication flow", explain=True)
for r in results:
    print(f"[{r.score:.3f}] {r.entry.content[:80]}")
    print(f"  matched: {r.matched_terms}  |  {r.explanation}")
```

### Hybrid Semantic Search

Plug in any embedding function to activate BM25+cosine hybrid scoring (40% BM25, 60% semantic):

```python
import openai

def my_embed(text: str) -> list[float]:
    resp = openai.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding

mem.set_embedding_fn(my_embed)  # hybrid activates automatically

# Or use a local model
import ollama
mem.set_embedding_fn(
    lambda text: ollama.embeddings(model="nomic-embed-text", prompt=text)["embedding"]
)
```

When no embedding function is set, search uses BM25 only (zero API calls).

---

## WAL Journaling

Every `ingest()` call appends to a write-ahead log before touching shard files. On crash, pending entries are replayed automatically on the next `load()`.

```python
mem.ingest("Important decision about the API design", source="meeting")
# Entry is now in the WAL — crash-safe

# WAL auto-flushes every 50 appends or at 1 MB
# Force-flush before backups:
mem.wal_flush()

# Check WAL health:
status = mem.wal_inspect()
print(f"{status['pending_entries']} entries pending ({status['size_bytes']} bytes)")
```

---

## Sharding

Memories are stored in date/category shards — plain JSON files you can inspect with any text editor.

```
workspace/
├── shards/
│   ├── 2026-02-strategic.json
│   ├── 2026-02-operational.json
│   └── 2026-01-tactical.json
├── indexes/
│   ├── search_index.json
│   ├── tag_index.json
│   └── date_index.json
├── .wal/
│   └── pending.jsonl          # Write-ahead log (auto-managed)
├── namespaces/
│   ├── project-alpha/         # Isolated namespace workspace
│   └── project-beta/
├── namespace_manifest.json
├── access_counts.json
├── outcomes.jsonl             # Retrieval feedback log
├── migrations/history.json
└── memory_audit.jsonl         # Deletion audit trail (GDPR)
```

---

## Decay

Retrieval scores combine **recency x importance x access frequency** using Ebbinghaus-inspired forgetting curves. Configurable half-life (default 7 days).

```python
mem = MemorySystem("./workspace", half_life=14.0)  # 14-day half-life

# Memory types override decay rates:
# - procedure/preference: 3x half-life (21 days with default)
# - mistake: 10x half-life (70 days with default)

# Compact to remove fully decayed entries
result = mem.compact()
print(f"Compacted {result['entries_before']} → {result['entries_after']} entries")
print(f"Freed {result['space_freed_mb']:.1f} MB")
```

---

## MCP Server

Expose your memory workspace as MCP tools for Claude Desktop, Cursor, or any MCP-compatible host.

```python
from antaris_memory import create_mcp_server  # pip install mcp

server = create_mcp_server("./workspace")
server.run()  # Stdio transport
```

MCP tools exposed: `memory_search`, `memory_ingest`, `memory_consolidate`, `memory_stats`.

```bash
# Or run directly from the CLI
antaris-memory-mcp --workspace ./workspace
```

---

## Input Gating (P0-P3)

```python
mem.ingest_with_gating("CRITICAL: API key compromised", source="alerts")
# P0 (critical) — stored with confidence 0.9

mem.ingest_with_gating("Decided to switch to PostgreSQL", source="meeting")
# P1 (operational) — stored

mem.ingest_with_gating("thanks for the update!", source="chat")
# P3 (ephemeral) — dropped silently
```

| Level | Category | Stored | Examples |
|-------|----------|--------|----------|
| P0 | Strategic | Yes | Security alerts, errors, deadlines |
| P1 | Operational | Yes | Decisions, assignments, technical choices |
| P2 | Tactical | Yes | Background info, research |
| P3 | — | No | Greetings, acknowledgments, filler |

Classification: keyword and pattern matching — no LLM calls. 0.177ms avg per input.

> **Note:** `ingest()` silently drops content shorter than **15 characters**. Single-concept memories ("Use Redis", "Done") fall below this threshold. Store them with a brief qualifier: `"Prefer Redis for caching"` (24 chars).

---

## Context Packets (Sub-Agent Injection)

```python
# Single-query context packet
packet = mem.build_context_packet(
    task="Debug the authentication flow",
    tags=["auth", "security"],
    max_memories=10,
    max_tokens=2000,
    include_mistakes=True,
)
print(packet.render("markdown"))  # structured markdown for prompt injection

# Multi-query with deduplication
packet = mem.build_context_packet_multi(
    task="Fix performance issues",
    queries=["database bottleneck", "slow queries", "caching strategy"],
    max_tokens=3000,
)
packet.trim(max_tokens=1500)
```

---

## Selective Forgetting (GDPR-ready)

```python
audit = mem.forget(entity="John Doe")       # Remove by entity
audit = mem.forget(topic="project alpha")    # Remove by topic
audit = mem.forget(before_date="2025-01-01") # Remove old entries
# Audit trail written to memory_audit.jsonl
```

---

## Shared Memory Pools

```python
from antaris_memory import SharedMemoryPool, AgentPermission

pool = SharedMemoryPool("./shared", pool_name="team-alpha")
pool.grant("agent-1", AgentPermission.READ_WRITE)
pool.grant("agent-2", AgentPermission.READ_ONLY)

mem_1 = pool.open("agent-1")
mem_1.ingest("Deployed new API endpoint")

mem_2 = pool.open("agent-2")
results = mem_2.search("API deployment")
```

---

## Concurrency

```python
from antaris_memory import FileLock

# Exclusive write access (atomic on all platforms including network filesystems)
with FileLock("/path/to/shard.json", timeout=10.0):
    data = load(shard)
    modify(data)
    save(shard, data)
```

---

## OpenClaw Integration

antaris-memory ships as a native OpenClaw plugin. Once enabled, the plugin fires automatically before and after each agent turn:

- `before_agent_start` — searches memory for relevant context, injects into agent prompt
- `agent_end` — ingests the turn into persistent memory

```bash
openclaw plugins enable antaris-memory
```

---

## What It Does

- **Sharded storage** for production scalability (10,000+ memories, sub-second search)
- **Fast search indexes** (full-text, tags, dates) stored as transparent JSON files
- **WAL journaling** for crash-safe ingestion with automatic replay
- **Namespace isolation** with hard boundaries between tenants, agents, or projects
- **Memory types** with distinct decay, importance, and recall behaviour
- **Retrieval feedback loop** adapts memory importance based on outcome signals
- **Bulk ingest** at 12,041 items/s with deferred O(1) index rebuild
- **Automatic schema migration** from single-file to sharded format with rollback
- **Multi-agent shared memory** pools with access controls
- Retrieval weighted by **recency x importance x access frequency** (Ebbinghaus-inspired decay)
- **Input gating** classifies incoming content by priority (P0-P3) and drops noise at intake
- Detects contradictions between stored memories using deterministic rule-based comparison
- Runs fully offline — zero network calls, zero tokens, zero API keys

## What It Doesn't Do

- **Not a vector database** — no embeddings by default. Core search uses BM25 keyword ranking. Semantic search requires you to supply an embedding function (`set_embedding_fn(fn)`).
- **Not a knowledge graph** — flat memory store with metadata indexing. No entity relationships or graph traversal.
- **Not semantic by default** — contradiction detection uses explicit conflict rules, not inference.
- **Not LLM-dependent** — all operations are deterministic. No model calls, no prompt engineering.
- **Not infinitely scalable** — JSON file storage works well up to ~50,000 memories per workspace.

---

## Benchmarks

Measured on Apple M4, Python 3.14.

| Memories | Ingest | Search (avg) | Search (p99) | Consolidate | Disk |
|----------|--------|-------------|-------------|-------------|------|
| 100 | 5.3ms (0.053ms/entry) | 0.40ms | 0.65ms | 4.2ms | 117KB |
| 500 | 16.8ms (0.034ms/entry) | 1.70ms | 2.51ms | 84.3ms | 575KB |
| 1,000 | 33.2ms (0.033ms/entry) | 3.43ms | 5.14ms | 343.3ms | 1.1MB |
| 5,000 | 173.7ms (0.035ms/entry) | 17.10ms | 25.70ms | 4.3s | 5.6MB |

**Bulk ingest:** 12,041 items/s | 1M entries in ~86s | near-flat scaling via deferred index rebuild

Input gating classification: **0.177ms avg** per input.

---

## Architecture

```
MemorySystemV4
├── ShardManager         — Date/topic sharding
├── IndexManager         — Full-text, tag, and date indexes
│   ├── SearchIndex      — BM25 inverted index
│   ├── TagIndex         — Tag → hash mapping
│   └── DateIndex        — Date range queries
├── SearchEngine         — BM25 + optional cosine hybrid
├── WALManager           — Write-ahead log (crash-safe ingestion)
├── ReadCache            — LRU search result cache
├── AccessTracker        — Per-entry access-count boosting
├── PerformanceMonitor   — Timing/counter stats
├── MigrationManager     — Schema versioning with rollback
├── InputGate            — P0-P3 classification at intake
├── DecayEngine          — Ebbinghaus forgetting curves
├── ConsolidationEngine  — Dedup, clustering, contradiction detection
├── ForgettingEngine     — Selective deletion with audit
├── RetrievalFeedback    — Outcome tracking + importance adaptation
├── SharedMemoryPool     — Multi-agent coordination
├── NamespaceManager     — Multi-tenant isolation
└── ContextPacketBuilder — Sub-agent context injection
```

---

## Running Tests

```bash
git clone https://github.com/Antaris-Analytics/antaris-memory.git
cd antaris-memory
python -m pytest tests/ -v
```

384 tests. All pass with zero external dependencies.

---

## Migrating from Earlier Versions

No breaking changes from v2.x. All new APIs (`bulk_ingest`, `record_outcome`, `feedback_stats`, etc.) are additive. Existing workspaces load automatically — no migration required.

For pre-3.0 stores using MD5 hashing, run `tools/migrate_hashes.py` to upgrade to BLAKE2b-128.

```bash
pip install --upgrade antaris-memory
```

---

## Zero Dependencies (Core)

The core package uses only the Python standard library. Optional extras:

- `pip install mcp` — enables `create_mcp_server()`
- Supply your own embedding function to `set_embedding_fn()` — any callable returning `list[float]` works (OpenAI, Ollama, sentence-transformers, etc.)

---

## Part of the Antaris Analytics Suite — v3.0.0

- **antaris-memory** — Persistent memory for AI agents (this package)
- **[antaris-router](https://pypi.org/project/antaris-router/)** — Adaptive model routing with SLA enforcement
- **[antaris-guard](https://pypi.org/project/antaris-guard/)** — Security and prompt injection detection
- **[antaris-context](https://pypi.org/project/antaris-context/)** — Context window optimization
- **[antaris-pipeline](https://pypi.org/project/antaris-pipeline/)** — Agent orchestration pipeline
- **[antaris-contracts](https://pypi.org/project/antaris-contracts/)** — Versioned schemas, failure semantics, and debug CLI

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.

---

**Built by Antaris Analytics**
*Deterministic infrastructure for AI agents*
