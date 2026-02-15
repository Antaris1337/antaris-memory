# Changelog

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
