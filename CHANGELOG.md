# Changelog

## [0.3.0] - 2026-02-15

### Added
- **Multi-Agent Shared Memory** (`SharedMemoryPool`): Multiple agents share a memory space with role-based access controls
- **Agent Permissions** (`AgentPermission`): Read, write, admin roles with namespace-level isolation
- **Namespace Isolation**: Agents only see memories in namespaces they have access to
- **Cross-Agent Conflict Detection**: Flags contradictions when agents write conflicting memories
- **Conflict Resolution**: Resolve disputes with audit trail
- **Knowledge Propagation**: Share discoveries from one agent's namespace to another
- **Pool Statistics**: Per-agent, per-namespace memory counts and conflict tracking
- 18 new tests for shared memory (40 total)

## [0.2.0] - 2026-02-15

### Added
- **Input Gating (P0-P3)**: Classify content at intake as Critical, Operational, Contextual, or Ephemeral. P3 content is automatically filtered out.
- **Autonomous Knowledge Synthesis**: Identify knowledge gaps, suggest research topics, and integrate new findings into memory.
- **`ingest_with_gating()`**: Smart ingestion that auto-classifies and routes content.
- **`research_suggestions()`**: Get prioritized research topics based on memory gaps.
- **`synthesize()`**: Integrate external research with existing memories.
- **OpenClaw integration example** (`examples/openclaw_integration.py`)
- **LangChain integration example** (`examples/langchain_integration.py`)
- 13 new tests (22 total)

## [0.1.1] - 2026-02-15

### Changed
- GitHub org renamed to Antaris-Analytics
- Updated project URLs
- Cleaned up README comparison table for accuracy
- Removed build artifacts from repo, added .gitignore

## [0.1.0] - 2026-02-15

### Added
- Initial release
- `MemorySystem` with ingest, search, save/load
- Ebbinghaus decay curves with reinforcement on access
- Sentiment tagging (positive, negative, urgent, strategic, financial)
- Temporal reasoning (date queries, range queries, narratives)
- Confidence scoring and contradiction detection
- Memory compression for old files
- Selective forgetting with GDPR-ready audit trail
- Dream-state consolidation (duplicate detection, topic clustering)
- Zero external dependencies
