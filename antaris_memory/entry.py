"""Memory entry — the atomic unit of memory."""

import hashlib
from datetime import datetime
from typing import Dict, List


class MemoryEntry:
    """Single memory unit with metadata, decay, sentiment, and confidence."""

    __slots__ = (
        "content", "source", "line", "category", "created",
        "last_accessed", "access_count", "importance", "confidence",
        "sentiment", "tags", "related", "hash",
    )

    def __init__(
        self,
        content: str,
        source: str = "",
        line: int = 0,
        category: str = "general",
        created: str = None,
    ):
        self.content = content
        self.source = source
        self.line = line
        self.category = category
        self.created = created or datetime.now().isoformat()
        self.last_accessed = self.created
        self.access_count: int = 0
        self.importance: float = 1.0
        self.confidence: float = 0.5
        self.sentiment: Dict[str, float] = {}
        self.tags: List[str] = []
        self.related: List[str] = []
        self.hash = hashlib.md5(
            f"{source}:{line}:{content[:100]}".encode()
        ).hexdigest()[:12]

    # -- serialisation --------------------------------------------------------

    def to_dict(self) -> Dict:
        return {
            "hash": self.hash,
            "content": self.content,
            "source": self.source,
            "line": self.line,
            "category": self.category,
            "created": self.created,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "importance": round(self.importance, 4),
            "confidence": round(self.confidence, 4),
            "sentiment": self.sentiment,
            "tags": self.tags,
            "related": self.related,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "MemoryEntry":
        m = cls(
            d["content"], d.get("source", ""), d.get("line", 0),
            d.get("category", "general"), d.get("created"),
        )
        m.last_accessed = d.get("last_accessed", m.created)
        m.access_count = d.get("access_count", 0)
        m.importance = d.get("importance", 1.0)
        m.confidence = d.get("confidence", 0.5)
        m.sentiment = d.get("sentiment", {})
        m.tags = d.get("tags", [])
        m.related = d.get("related", [])
        m.hash = d.get("hash", m.hash)
        return m

    def __repr__(self) -> str:
        return f"<Memory {self.hash} score={self.importance:.2f} conf={self.confidence:.2f}>"
