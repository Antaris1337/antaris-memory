"""
Context packets — structured memory injection for sub-agent spawning.

Solves the "cold spawn" problem: sub-agents start with zero context,
leading to confident mistakes based on incomplete information.

A ContextPacket bundles relevant memories, environment details, and
task-specific context into a structured block that can be injected
into a sub-agent's prompt at spawn time.

Usage:
    from antaris_memory import MemorySystem

    mem = MemorySystem("./workspace")
    mem.load()

    # Build a context packet for a sub-agent task
    packet = mem.build_context_packet(
        task="Verify antaris-guard installation in venv-svi",
        tags=["antaris-guard", "installation"],
        environment={"venv": "venv-svi", "python": "3.11"},
        max_memories=10,
        max_tokens=2000,
    )

    # Inject into sub-agent prompt
    prompt = f\""\"
    {packet.render()}

    YOUR TASK: {task_description}
    \""\"

    # Or get it as a dict for structured passing
    data = packet.to_dict()
"""

import hashlib
import html
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ContextPacket:
    """A structured context bundle for sub-agent spawning.

    Contains relevant memories, environment details, and metadata
    needed for a sub-agent to operate with proper context.

    Attributes:
        task: The task description this packet was built for.
        memories: List of (content, score, source, category) tuples.
        environment: Key-value pairs describing the execution environment.
        instructions: Explicit instructions or constraints for the sub-agent.
        metadata: Build metadata (timestamp, query used, memory count).
    """

    task: str
    memories: List[Dict[str, Any]] = field(default_factory=list)
    environment: Dict[str, str] = field(default_factory=dict)
    instructions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def render(self, fmt: str = "markdown") -> str:
        """Render the packet as injectable text.

        Args:
            fmt: Output format — "markdown" (default) or "xml" or "json".

        Returns:
            Formatted string ready for prompt injection.
        """
        if fmt == "json":
            return json.dumps(self.to_dict(), indent=2)
        elif fmt == "xml":
            return self._render_xml()
        else:
            return self._render_markdown()

    def _render_markdown(self) -> str:
        lines = ["## Context Packet", ""]

        if self.environment:
            lines.append("### Environment")
            for k, v in self.environment.items():
                lines.append(f"- **{k}:** {v}")
            lines.append("")

        if self.instructions:
            lines.append("### Instructions")
            for inst in self.instructions:
                lines.append(f"- {inst}")
            lines.append("")

        if self.memories:
            lines.append("### Relevant Context")
            for i, mem in enumerate(self.memories, 1):
                content = mem["content"]
                source = mem.get("source", "")
                score = mem.get("score", 0)
                source_tag = f" *(from: {source})*" if source else ""
                lines.append(f"{i}. {content}{source_tag}")
            lines.append("")

        if self.metadata:
            built = self.metadata.get("built_at", "")
            count = self.metadata.get("total_memories_searched", 0)
            lines.append(
                f"*Packet built {built} — searched {count} memories, "
                f"returned {len(self.memories)} relevant.*"
            )

        return "\n".join(lines)

    def _render_xml(self) -> str:
        lines = ["<context_packet>"]

        if self.environment:
            lines.append("  <environment>")
            for k, v in self.environment.items():
                lines.append(
                    f'    <var name="{html.escape(str(k))}">{html.escape(str(v))}</var>'
                )
            lines.append("  </environment>")

        if self.instructions:
            lines.append("  <instructions>")
            for inst in self.instructions:
                lines.append(f"    <instruction>{html.escape(inst)}</instruction>")
            lines.append("  </instructions>")

        if self.memories:
            lines.append("  <relevant_context>")
            for mem in self.memories:
                source = html.escape(mem.get("source", ""))
                content = html.escape(mem["content"])
                lines.append(f'    <memory source="{source}">{content}</memory>')
            lines.append("  </relevant_context>")

        lines.append("</context_packet>")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the packet to a dictionary."""
        return {
            "task": self.task,
            "memories": self.memories,
            "environment": self.environment,
            "instructions": self.instructions,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextPacket":
        """Deserialize a packet from a dictionary."""
        return cls(
            task=data.get("task", ""),
            memories=data.get("memories", []),
            environment=data.get("environment", {}),
            instructions=data.get("instructions", []),
            metadata=data.get("metadata", {}),
        )

    def __len__(self) -> int:
        """Number of memories in the packet."""
        return len(self.memories)

    def __bool__(self) -> bool:
        """True if the packet contains any context."""
        return bool(self.memories or self.environment or self.instructions)

    @property
    def estimated_tokens(self) -> int:
        """Rough token estimate for the rendered packet (len/4 heuristic).

        Based on markdown rendering. XML/JSON output may differ slightly.
        """
        return len(self.render()) // 4

    def trim(self, max_tokens: int) -> "ContextPacket":
        """Return a new packet trimmed to fit within a token budget.

        Removes memories from the tail (lowest relevance) until
        the rendered output fits within max_tokens.
        """
        if self.estimated_tokens <= max_tokens:
            return self

        trimmed = ContextPacket(
            task=self.task,
            memories=list(self.memories),
            environment=dict(self.environment),
            instructions=list(self.instructions),
            metadata=dict(self.metadata),
        )

        while trimmed.memories and trimmed.estimated_tokens > max_tokens:
            trimmed.memories.pop()

        trimmed.metadata["trimmed_to"] = max_tokens
        trimmed.metadata["memories_after_trim"] = len(trimmed.memories)
        return trimmed

    def __repr__(self) -> str:
        return (
            f"<ContextPacket task='{self.task[:40]}...' "
            f"memories={len(self.memories)} "
            f"~{self.estimated_tokens} tokens>"
        )


class ContextPacketBuilder:
    """Builds context packets from a MemorySystem.

    Pulls relevant memories via BM25 search, applies filters,
    and packages them with environment and instruction context.

    Args:
        memory_system: A loaded MemorySystem instance.
    """

    def __init__(self, memory_system):
        self.mem = memory_system

    def build(
        self,
        task: str,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        instructions: Optional[List[str]] = None,
        max_memories: int = 15,
        max_tokens: int = 4000,
        min_relevance: float = 0.1,
        include_sources: bool = True,
    ) -> ContextPacket:
        """Build a context packet for a sub-agent task.

        Searches the memory store for relevant context and packages it
        into a structured ContextPacket.

        Args:
            task: Description of the sub-agent's task (used as search query).
            tags: Optional tag filters to narrow search.
            category: Optional category filter.
            environment: Key-value pairs for the execution environment.
            instructions: Explicit instructions for the sub-agent.
            max_memories: Maximum memories to include (default 15).
            max_tokens: Token budget for the rendered packet (default 4000).
            min_relevance: Minimum relevance score (0.0–1.0 normalized) to include.
                Score vs relevance: score is raw BM25 output, relevance is
                normalized to 0.0–1.0 where 1.0 = best match in the result set.
                Filtering uses relevance; output includes raw score for debugging.
            include_sources: Whether to include source attribution (default True).

        Returns:
            A ContextPacket ready for injection into a sub-agent prompt.
        """
        # Validate min_relevance (0.0–1.0 scale, not percentage)
        if min_relevance > 1.0:
            raise ValueError(
                f"min_relevance={min_relevance} looks like a percentage. "
                f"Use 0.0–1.0 scale (e.g. 0.1 = 10%)."
            )

        # Search for relevant memories using the task as query
        results = self.mem.search(
            query=task,
            limit=max_memories * 3,  # Over-fetch to allow for filtering
            category=category,
            explain=True,
        )

        # Filter by relevance and tags, build memory list
        memories = []
        for r in results:
            # Tag filter: if tags specified, entry must have at least one matching tag
            if tags and hasattr(r.entry, "tags") and r.entry.tags:
                entry_tags = {et.lower() for et in r.entry.tags}
                if not any(t.lower() in entry_tags for t in tags):
                    continue
            elif tags and (not hasattr(r.entry, "tags") or not r.entry.tags):
                continue  # Tags requested but entry has none
            if r.relevance < min_relevance:
                continue
            if len(memories) >= max_memories:
                break

            mem_dict = {"content": r.content, "score": round(r.score, 3)}
            if include_sources and r.source:
                mem_dict["source"] = r.source
            if hasattr(r.entry, "category") and r.entry.category:
                mem_dict["category"] = r.entry.category
            if hasattr(r.entry, "tags") and r.entry.tags:
                mem_dict["tags"] = r.entry.tags

            memories.append(mem_dict)

        # Build metadata
        metadata = {
            "built_at": datetime.now().isoformat(),
            "query": task,
            "total_memories_searched": len(self.mem.memories),
            "results_found": len(results),
            "results_included": len(memories),
        }
        if tags:
            metadata["tag_filter"] = tags
        if category:
            metadata["category_filter"] = category

        packet = ContextPacket(
            task=task,
            memories=memories,
            environment=environment or {},
            instructions=instructions or [],
            metadata=metadata,
        )

        # Trim to token budget
        if packet.estimated_tokens > max_tokens:
            packet = packet.trim(max_tokens)

        return packet

    def build_multi(
        self,
        task: str,
        queries: List[str],
        environment: Optional[Dict[str, str]] = None,
        instructions: Optional[List[str]] = None,
        max_memories: int = 15,
        max_tokens: int = 4000,
        min_relevance: float = 0.1,
    ) -> ContextPacket:
        """Build a packet from multiple search queries.

        Useful when a task spans multiple topics. Deduplicates results
        by memory hash and merges into a single packet.

        Args:
            task: The overall task description.
            queries: List of search queries to run.
            environment: Optional environment context.
            instructions: Optional instructions.
            max_memories: Max total memories across all queries.
            max_tokens: Token budget.
            min_relevance: Minimum relevance threshold.

        Returns:
            A merged ContextPacket with deduplicated results.
        """
        seen_hashes = set()
        all_memories = []

        per_query_limit = max(max_memories // len(queries), 5)

        for query in queries:
            results = self.mem.search(
                query=query,
                limit=per_query_limit * 2,
                explain=True,
            )

            for r in results:
                if r.relevance < min_relevance:
                    continue
                # Dedup by entry hash, falling back to stable content digest
                entry_hash = getattr(r.entry, "hash", None)
                if not entry_hash:
                    entry_hash = hashlib.sha1(r.content.encode("utf-8")).hexdigest()
                if entry_hash in seen_hashes:
                    continue
                seen_hashes.add(entry_hash)

                all_memories.append({
                    "content": r.content,
                    "score": round(r.score, 3),
                    "source": r.source if r.source else "",
                    "query": query,
                })

        # Sort by score descending, take top N
        all_memories.sort(key=lambda m: m["score"], reverse=True)
        all_memories = all_memories[:max_memories]

        metadata = {
            "built_at": datetime.now().isoformat(),
            "queries": queries,
            "total_memories_searched": len(self.mem.memories),
            "results_included": len(all_memories),
        }

        packet = ContextPacket(
            task=task,
            memories=all_memories,
            environment=environment or {},
            instructions=instructions or [],
            metadata=metadata,
        )

        if packet.estimated_tokens > max_tokens:
            packet = packet.trim(max_tokens)

        return packet
