"""Claim 16: Memory decay & reinforcement using Ebbinghaus-inspired curves."""

import math
from datetime import datetime
from .entry import MemoryEntry

# Defaults — users can override via MemorySystem config
DEFAULT_HALF_LIFE = 7.0  # days
ARCHIVE_THRESHOLD = 0.15
REINFORCEMENT_BOOST = 0.25
MAX_SCORE = 2.0


class DecayEngine:
    """Ebbinghaus-inspired memory decay with reinforcement on access."""

    def __init__(self, half_life: float = DEFAULT_HALF_LIFE,
                 archive_threshold: float = ARCHIVE_THRESHOLD,
                 reinforcement_boost: float = REINFORCEMENT_BOOST,
                 max_score: float = MAX_SCORE):
        self.half_life = half_life
        self.archive_threshold = archive_threshold
        self.reinforcement_boost = reinforcement_boost
        self.max_score = max_score

    def score(self, entry: MemoryEntry, now: datetime = None) -> float:
        """Calculate current memory strength after decay + reinforcement."""
        now = now or datetime.now()
        created = datetime.fromisoformat(entry.created)
        age_days = max((now - created).total_seconds() / 86400, 0.001)

        base_decay = entry.importance * math.pow(2, -age_days / self.half_life)
        reinforcement = (
            entry.access_count * self.reinforcement_boost
            * math.pow(2, -age_days / (self.half_life * 2))
        )
        return round(min(base_decay + reinforcement, self.max_score), 4)

    def reinforce(self, entry: MemoryEntry) -> None:
        """Boost a memory when it's accessed."""
        entry.access_count += 1
        entry.last_accessed = datetime.now().isoformat()
        entry.importance = min(
            entry.importance + 0.1 / (1 + entry.access_count * 0.1),
            self.max_score,
        )

    def should_archive(self, entry: MemoryEntry, now: datetime = None) -> bool:
        """True if this memory has decayed below the archive threshold."""
        return self.score(entry, now) < self.archive_threshold
