# antaris-memory

**Production-ready file-based persistent memory for AI agents. Zero dependencies (core).**

Store, search, decay, and consolidate agent memories using only the Python standard library. Sharded storage for scalability, fast search indexes, namespace isolation, MCP server support, and automatic schema migration. No vector databases, no infrastructure, no API keys.

[![PyPI](https://img.shields.io/pypi/v/antaris-memory)](https://pypi.org/project/antaris-memory/)
[![Tests](https://github.com/Antaris-Analytics/antaris-memory/actions/workflows/tests.yml/badge.svg)](https://github.com/Antaris-Analytics/antaris-memory/actions/workflows/tests.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-orange.svg)](LICENSE)

## What's New in v2.4.0 (antaris-suite 3.0)

- **`bulk_ingest(entries)`** — O(1) deferred index rebuild; ingest 1M entries without O(n²) WAL flush penalty
- **`with mem.bulk_mode():`** — context manager for existing `ingest()` call sites; single index rebuild on exit
- **Retrieval Feedback Loop** — `record_outcome(ids, "good"|"bad"|"neutral")` adapts memory importance in real time
- **BLAKE2b-128 hashing** — replaces MD5 for entry deduplication (SEC-001); `tools/migrate_hashes.py` for pre-3.0 stores
- **Audit log** — `memory_audit.json` → `memory_audit.jsonl`; O(1) append per entry, no full-file rewrite
- **Cross-platform locking** — `_pid_running()` uses ctypes/OpenProcess on Windows, os.kill(pid,0) on POSIX


- **Production Cleanup API** — `purge()`, `rebuild_indexes()`, `wal_flush()`, `wal_inspect()` — bulk removal, index repair, and WAL management without manual shard surgery (see [Production Cleanup API](#-production-cleanup-api-v210))
- **WAL subsystem** — write-ahead log for safe, fast ingestion; auto-flushes every 50 appends or at 1 MB; crash-safe replay on startup
- **LRU read cache** — Sprint 11 search caching with access-count boosting; configurable size via `cache_max_entries`
- **`purge()` glob patterns** — `source="pipeline:pipeline_*"` removes all memories from any pipeline session at once

Previous v2.0.0 highlights (still fully available):

- **MCP Server** — expose your memory workspace as MCP tools via `create_mcp_server()` (requires `pip install mcp`)
- **Hybrid semantic search** — plug in any embedding function with `set_embedding_fn(fn)`; BM25 and cosine blend automatically
- **Memory types** — typed ingestion: `episodic`, `semantic`, `procedural`, `preference`, `mistake` — each with recall priority boosts
- **Namespace isolation** — `NamespacedMemory` and `NamespaceManager` for multi-tenant memory with hard boundaries
- **Context packets** — `build_context_packet()` packages relevant memories for sub-agent injection with token budgeting
- 293 tests (all passing)

See [CHANGELOG.md](CHANGELOG.md) for full version history.

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
mem.ingest_mistake("Forgot to close DB connections in worker threads")
mem.ingest_procedure("Deploy: push to main → CI runs → auto-deploy to staging")

# Input gating — drops ephemeral noise (P3) before storage
mem.ingest_with_gating("Decided to switch to Redis for caching", source="chat")
mem.ingest_with_gating("thanks for the update!", source="chat")  # → dropped (P3)

# Search (BM25; hybrid BM25+cosine if embedding fn set)
for r in mem.search("database decision"):
    print(f"[{r.confidence:.2f}] {r.content}")

# Save
mem.save()
```

---

## 🧹 Production Cleanup API (v2.1.0)

These four methods replace manual shard surgery for production maintenance.
Use them after bulk imports, pipeline restarts, or to clean up test data.

### `purge()` — Bulk removal with glob patterns

Remove memories by source, content substring, or custom predicate. The WAL is
filtered too, so purged entries cannot be replayed on the next `load()`.

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

Call after any bulk change (purge, manual shard edits, imports) to ensure the
search index matches live data.

```python
result = mem.rebuild_indexes()
print(f"Indexed {result['memories']} memories, {result['words_indexed']} words")
# → {"memories": 9990, "words_indexed": 5800, "tags": 24}
```

### `wal_flush()` — Force-flush WAL to shard files

Normally the WAL auto-flushes. Call this explicitly before making backups,
running migrations, or reading shard files directly.

```python
flushed = mem.wal_flush()
print(f"Flushed {flushed} pending WAL entries to shards")
```

### `wal_inspect()` — Health check without mutating state

```python
status = mem.wal_inspect()
# {
#     "pending_entries": 14,
#     "size_bytes": 8192,
#     "sample": ["content preview 1...", "content preview 2..."]
# }
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

## OpenClaw Integration

antaris-memory ships as a native OpenClaw plugin (`antaris-memory`). Once
enabled, the plugin fires automatically before and after each agent turn:

- `before_agent_start` — searches memory for relevant context, injects into agent prompt
- `agent_end` — ingests the turn into persistent memory

```bash
openclaw plugins enable antaris-memory
```

Also ships with an MCP server for any MCP-compatible host:

```python
from antaris_memory import create_mcp_server  # pip install mcp
server = create_mcp_server(workspace="./memory")
server.run()  # MCP tools: memory_search, memory_ingest, memory_consolidate, memory_stats
```

---

## What It Does

- **Sharded storage** for production scalability (10,000+ memories, sub-second search)
- **Fast search indexes** (full-text, tags, dates) stored as transparent JSON files
- **Automatic schema migration** from single-file to sharded format with rollback
- **Multi-agent shared memory** pools with namespace isolation and access controls
- Retrieval weighted by **recency × importance × access frequency** (Ebbinghaus-inspired decay)
- **Input gating** classifies incoming content by priority (P0–P3) and drops ephemeral noise at intake
- Detects contradictions between stored memories using deterministic rule-based comparison
- Runs fully offline — zero network calls, zero tokens, zero API keys

## What It Doesn't Do

- **Not a vector database** — no embeddings by default. Core search uses BM25 keyword ranking. Semantic search requires you to supply an embedding function (`set_embedding_fn(fn)`) — we never make that call for you.
- **Not a knowledge graph** — flat memory store with metadata indexing. No entity relationships or graph traversal.
- **Not semantic by default** — contradiction detection compares normalized statements using explicit conflict rules, not inference.
- **Not LLM-dependent** — all operations are deterministic. No model calls, no prompt engineering.
- **Not infinitely scalable** — JSON file storage works well up to ~50,000 memories per workspace.

---

## Memory Types

```python
mem.ingest("Deploy: push to main, CI runs, auto-deploy to staging",
           memory_type="procedural")   # High recall boost for how-to queries
mem.ingest_fact("PostgreSQL supports JSONB indexing")   # Semantic memory
mem.ingest_preference("User prefers Python examples")   # Preference memory
mem.ingest_mistake("Forgot to handle connection timeout")  # Mistake memory
mem.ingest_procedure("Run pytest from venv, not global pip")  # Procedure
```

| Type | Use for | Recall boost |
|------|---------|-------------|
| `episodic` | Events, decisions, meeting notes | Normal |
| `semantic` | Facts, concepts, general knowledge | Medium |
| `procedural` | How-to steps, runbooks | High |
| `preference` | User preferences, style notes | High |
| `mistake` | Errors to avoid, lessons learned | High |

---

## Hybrid Semantic Search

```python
import openai

def my_embed(text: str) -> list[float]:
    resp = openai.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding

mem.set_embedding_fn(my_embed)  # BM25+cosine hybrid activates automatically

# Or use a local model
import ollama
mem.set_embedding_fn(
    lambda text: ollama.embeddings(model="nomic-embed-text", prompt=text)["embedding"]
)
```

When no embedding function is set, search uses BM25 only (zero API calls).

---

## Input Gating (P0–P3)

```python
mem.ingest_with_gating("CRITICAL: API key compromised", source="alerts")
# → P0 (critical) → stored with confidence 0.9

mem.ingest_with_gating("Decided to switch to PostgreSQL", source="meeting")
# → P1 (operational) → stored

mem.ingest_with_gating("thanks for the update!", source="chat")
# → P3 (ephemeral) → dropped silently
```

| Level | Category | Stored | Examples |
|-------|----------|--------|----------|
| P0 | Strategic | ✅ | Security alerts, errors, deadlines |
| P1 | Operational | ✅ | Decisions, assignments, technical choices |
| P2 | Tactical | ✅ | Background info, research |
| P3 | — | ❌ | Greetings, acknowledgments, filler |

Classification: keyword and pattern matching — no LLM calls. 0.177ms avg per input.

> **Note:** `ingest()` (and `ingest_with_gating()`) silently drops content shorter than
> **15 characters**.  Single-concept memories ("Use Redis", "Done") fall below this threshold.
> Store them with a brief qualifier: `"Prefer Redis for caching"` (24 chars → stored).

---

## Namespace Isolation

```python
from antaris_memory import NamespacedMemory, NamespaceManager

manager = NamespaceManager("./workspace")
agent_a = manager.create_namespace("agent-a")
agent_b = manager.create_namespace("agent-b")

ns = NamespacedMemory("project-alpha", "./workspace")
ns.load()
ns.ingest("Alpha-specific decision")
results = ns.search("decision")
```

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
print(packet.render("markdown"))  # → structured markdown for prompt injection

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
audit = mem.forget(topic="project alpha")   # Remove by topic
audit = mem.forget(before_date="2025-01-01")  # Remove old entries
# Audit trail written to memory_audit.json
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
from antaris_memory import FileLock, VersionTracker

# Exclusive write access (atomic on all platforms including network filesystems)
with FileLock("/path/to/shard.json", timeout=10.0):
    data = load(shard)
    modify(data)
    save(shard, data)
```

---

## Storage Format

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
├── access_counts.json          # Access-frequency tracker
├── migrations/history.json
└── memory_audit.json           # Deletion audit trail (GDPR)
```

Plain JSON files. Inspect or edit with any text editor.

---

## Architecture

```
MemorySystem (v2.1)
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
├── SharedMemoryPool     — Multi-agent coordination
├── NamespaceManager     — Multi-tenant isolation
└── ContextPacketBuilder — Sub-agent context injection
```

---

## Benchmarks

Measured on Apple M4, Python 3.14.

| Memories | Ingest | Search (avg) | Search (p99) | Consolidate | Disk |
|----------|--------|-------------|-------------|-------------|------|
| 100 | 5.3ms (0.053ms/entry) | 0.40ms | 0.65ms | 4.2ms | 117KB |
| 500 | 16.8ms (0.034ms/entry) | 1.70ms | 2.51ms | 84.3ms | 575KB |
| 1,000 | 33.2ms (0.033ms/entry) | 3.43ms | 5.14ms | 343.3ms | 1.1MB |
| 5,000 | 173.7ms (0.035ms/entry) | 17.10ms | 25.70ms | 4.3s | 5.6MB |

Input gating classification: **0.177ms avg** per input.

---

## Large Corpus Management

antaris-memory can ingest at **1M+ items** using `bulk_ingest()` (11,600 items/s on M4 hardware).
At runtime, however, a safety limit caps the active in-memory set to **20,000 entries** by default.
This is a deliberate design choice — searching across millions of live entries would require a different
index architecture (approximate nearest-neighbour, etc.).

**What this means in practice:**

```python
# This completes in ~86s for 1M items:
mem.bulk_ingest(corpus_generator())  # all entries written to shards on disk

# On the next load(), only the 20K highest-scoring entries are loaded into RAM:
mem.load()  # prints a UserWarning if the corpus exceeds the limit
```

A `UserWarning` is emitted when the limit is hit so you won't miss it in logs.

**Working with large corpora:**

```python
# Compact the corpus: dedup + consolidate, then trim to high-value entries
mem.compact()

# Archive old shards to keep the active set small
# (shards are plain JSON — archive to S3, local disk, etc.)

# Raise the limit explicitly (advanced — ensure you have enough RAM):
# Set _LOAD_LIMIT in core_v4._load_sharded() or subclass MemorySystemV4.
```

> **Rule of thumb:** For typical agent use (10K–100K active memories), search latency stays under 5ms.
> At 1M loaded entries (with raised limit), p50 search is ~2.4s — plan accordingly.

---

## MCP Server

```python
from antaris_memory import create_mcp_server  # pip install mcp

server = create_mcp_server("./workspace")
server.run()  # Stdio transport — connect from Claude Desktop, Cursor, etc.
```

MCP tools exposed: `memory_search`, `memory_ingest`, `memory_consolidate`, `memory_stats`.

---

## Running Tests

```bash
git clone https://github.com/Antaris-Analytics/antaris-memory.git
cd antaris-memory
python -m pytest tests/ -v
```

All 293 tests pass with zero external dependencies.

---

## Migrating from v2.0.0

No breaking changes. The new `purge()`, `rebuild_indexes()`, `wal_flush()`, and
`wal_inspect()` methods are additive. Existing workspaces load automatically —
no migration required.

```bash
pip install --upgrade antaris-memory
```

## Migrating from v1.x

```python
# Existing workspaces load automatically — no changes required
mem = MemorySystem("./existing_workspace")
mem.load()  # Auto-detects format, migrates if needed
```

---

## Zero Dependencies (Core)

The core package uses only the Python standard library. Optional extras:

- `pip install mcp` — enables `create_mcp_server()`
- Supply your own embedding function to `set_embedding_fn()` — any callable returning `list[float]` works (OpenAI, Ollama, sentence-transformers, etc.)

---

## Part of the Antaris Analytics Suite

- **antaris-memory** — Persistent memory for AI agents (this package)
- **[antaris-router](https://pypi.org/project/antaris-router/)** — Adaptive model routing with SLA enforcement
- **[antaris-guard](https://pypi.org/project/antaris-guard/)** — Security and prompt injection detection
- **[antaris-context](https://pypi.org/project/antaris-context/)** — Context window optimization
- **[antaris-pipeline](https://pypi.org/project/antaris-pipeline/)** — Agent orchestration pipeline

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.

---

**Built with ❤️ by Antaris Analytics**  
*Deterministic infrastructure for AI agents*
