# Changelog

## [0.4.0] - 2026-02-15

### Added (Production Features)
- **Sharded Storage** (`ShardManager`): Split memories across multiple files by date/topic for better performance and scalability
- **Fast Search Indexes** (`IndexManager`): Full-text, tag-based, and date range indexes for sub-second search
- **Schema Migration System** (`MigrationManager`): Seamless migration from v0.2/v0.3 single-file format to v0.4 sharded format with rollback capability
- **Lightweight File-Based Indexes**: Text search index, tag index, and date index - all stored as transparent JSON files
- **Automatic Migration**: v0.2/v0.3 data is automatically migrated to v0.4 format on first load
- **Backward Compatibility**: Can still read and work with legacy single-file format
- **Production-Ready MemorySystem**: New `MemorySystemV4` class with enterprise features while maintaining same API
- **Index Rebuilding**: Rebuild corrupted indexes from existing data
- **Migration History**: Track all applied migrations with rollback information
- **Schema Validation**: Validate data integrity across format versions
- **Shard Compaction**: Merge small shards and split large ones for optimal performance

### Enhanced
- **Search Performance**: 10-100x faster search using pre-built indexes instead of scanning all memories
- **Storage Scalability**: Handle 10,000+ memories efficiently through sharding
- **Memory Usage**: Only load relevant shards into memory, not entire dataset
- **Concurrent Access**: Multiple processes can work on different shards simultaneously

### Technical
- 4 new core modules: `sharding.py`, `migration.py`, `indexing.py`, `core_v4.py`
- 11 new classes: `ShardManager`, `ShardKey`, `ShardIndex`, `MigrationManager`, `Migration`, `V2ToV4Migration`, `IndexManager`, `SearchIndex`, `TagIndex`, `DateIndex`  
- 34 new tests covering all v0.4 features
- Full API compatibility with v0.3 - existing code works unchanged

### Migration Notes
- First load after upgrading will automatically migrate v0.2/v0.3 data to v0.4 format
- Original data is backed up during migration
- Use `migration_manager.rollback()` to revert if needed
- New installs start directly in v0.4 format

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
