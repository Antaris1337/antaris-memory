"""
Shared Memory — Multi-agent memory pools with access controls.

Enables multiple agents to share a memory space with:
- Role-based access (read, write, admin)
- Per-agent namespaces with optional sharing
- Conflict resolution when agents disagree
- Knowledge propagation between agents
- Audit trail of who wrote/modified what

All data stored as JSON files. Zero dependencies.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .entry import MemoryEntry
from .decay import DecayEngine
from .sentiment import SentimentTagger


class AgentPermission:
    """Access control for a single agent."""

    __slots__ = ("agent_id", "role", "namespaces", "created")

    ROLES = ("read", "write", "admin")

    def __init__(self, agent_id: str, role: str = "write",
                 namespaces: List[str] = None):
        if role not in self.ROLES:
            raise ValueError(f"Role must be one of {self.ROLES}")
        self.agent_id = agent_id
        self.role = role
        self.namespaces = namespaces or ["shared"]
        self.created = datetime.now().isoformat()

    def can_read(self) -> bool:
        return self.role in ("read", "write", "admin")

    def can_write(self) -> bool:
        return self.role in ("write", "admin")

    def can_admin(self) -> bool:
        return self.role == "admin"

    def can_access_namespace(self, namespace: str) -> bool:
        if self.role == "admin":
            return True
        return namespace in self.namespaces or namespace == "shared"

    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "namespaces": self.namespaces,
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "AgentPermission":
        perm = cls(d["agent_id"], d.get("role", "write"),
                   d.get("namespaces", ["shared"]))
        perm.created = d.get("created", perm.created)
        return perm


class SharedMemoryPool:
    """Multi-agent shared memory with access controls and conflict resolution.

    Parameters
    ----------
    pool_dir : str
        Directory for the shared memory pool.
    pool_name : str
        Name of the pool (used in filenames).
    """

    def __init__(self, pool_dir: str, pool_name: str = "default"):
        self.pool_dir = os.path.abspath(pool_dir)
        self.pool_name = pool_name
        self.state_path = os.path.join(self.pool_dir,
                                        f"pool_{pool_name}.json")
        self.audit_path = os.path.join(self.pool_dir,
                                        f"pool_{pool_name}_audit.json")

        # Internal state
        self.memories: List[MemoryEntry] = []
        self.permissions: Dict[str, AgentPermission] = {}
        self.conflicts: List[Dict] = []
        self._hashes: set = set()
        self._decay = DecayEngine(half_life=7.0)
        self._sentiment = SentimentTagger()

        os.makedirs(self.pool_dir, exist_ok=True)

    # ── agent management ────────────────────────────────────────────────

    def register_agent(self, agent_id: str, role: str = "write",
                       namespaces: List[str] = None) -> AgentPermission:
        """Register an agent with the pool."""
        perm = AgentPermission(agent_id, role, namespaces)
        self.permissions[agent_id] = perm
        self._audit("register", agent_id, f"role={role}")
        return perm

    def remove_agent(self, agent_id: str, requester: str = None) -> bool:
        """Remove an agent from the pool. Requires admin."""
        if requester and not self._check_admin(requester):
            return False
        if agent_id in self.permissions:
            del self.permissions[agent_id]
            self._audit("remove_agent", requester or "system",
                        f"removed={agent_id}")
            return True
        return False

    def list_agents(self) -> List[Dict]:
        """List all registered agents and their roles."""
        return [p.to_dict() for p in self.permissions.values()]

    # ── memory operations ───────────────────────────────────────────────

    def write(self, agent_id: str, content: str, namespace: str = "shared",
              category: str = "general", metadata: Dict = None) -> Optional[MemoryEntry]:
        """Write a memory to the pool. Checks permissions."""
        perm = self.permissions.get(agent_id)
        if not perm:
            return None
        if not perm.can_write():
            return None
        if not perm.can_access_namespace(namespace):
            return None

        entry = MemoryEntry(content, source=f"agent:{agent_id}",
                            category=category)
        entry.sentiment = self._sentiment.analyze(content)

        # Add agent metadata
        if not hasattr(entry, 'metadata'):
            entry.related = []
        entry.tags.append(f"ns:{namespace}")
        entry.tags.append(f"agent:{agent_id}")
        if metadata:
            for k, v in metadata.items():
                entry.tags.append(f"{k}:{v}")

        # Check for conflicts with existing memories
        conflict = self._check_conflict(entry, agent_id)
        if conflict:
            self.conflicts.append(conflict)

        if entry.hash not in self._hashes:
            self.memories.append(entry)
            self._hashes.add(entry.hash)
            self._audit("write", agent_id,
                        f"ns={namespace} hash={entry.hash}")
            return entry
        return None

    def read(self, agent_id: str, query: str, namespace: str = None,
             limit: int = 20) -> List[MemoryEntry]:
        """Search shared memories. Respects namespace permissions."""
        perm = self.permissions.get(agent_id)
        if not perm or not perm.can_read():
            return []

        import re
        q = query.lower()
        q_words = set(re.findall(r"\w{3,}", q))
        results = []

        for m in self.memories:
            # Check namespace access
            m_ns = self._get_namespace(m)
            if namespace and m_ns != namespace:
                continue
            if not perm.can_access_namespace(m_ns):
                continue

            # Score
            c = m.content.lower()
            score = 0.0
            if q in c:
                score += 3.0
            else:
                c_words = set(re.findall(r"\w{3,}", c))
                overlap = len(q_words & c_words) / max(len(q_words), 1)
                score += overlap * 2.0

            decay_score = self._decay.score(m)
            score *= (0.5 + decay_score)

            if score > 0.3:
                results.append((m, score))
                self._decay.reinforce(m)

        results.sort(key=lambda x: x[1], reverse=True)
        self._audit("read", agent_id, f"query={query[:50]} results={len(results)}")
        return [m for m, _ in results[:limit]]

    def propagate(self, from_agent: str, to_namespace: str,
                  query: str = None, limit: int = 10) -> int:
        """Propagate an agent's memories to another namespace.

        Useful for sharing discoveries across agent teams.
        """
        perm = self.permissions.get(from_agent)
        if not perm or not perm.can_write():
            return 0

        # Find memories written by this agent
        agent_memories = [m for m in self.memories
                          if f"agent:{from_agent}" in m.tags]

        if query:
            import re
            q = query.lower()
            q_words = set(re.findall(r"\w{3,}", q))
            scored = []
            for m in agent_memories:
                c = m.content.lower()
                overlap = len(q_words & set(re.findall(r"\w{3,}", c)))
                if overlap > 0:
                    scored.append((m, overlap))
            scored.sort(key=lambda x: x[1], reverse=True)
            agent_memories = [m for m, _ in scored[:limit]]
        else:
            agent_memories = agent_memories[:limit]

        count = 0
        for m in agent_memories:
            # Create a copy in the target namespace
            new_entry = MemoryEntry(
                m.content,
                source=f"propagated:{from_agent}",
                category=m.category,
            )
            new_entry.tags = list(m.tags)
            # Replace namespace tag
            new_entry.tags = [t for t in new_entry.tags
                              if not t.startswith("ns:")]
            new_entry.tags.append(f"ns:{to_namespace}")
            new_entry.tags.append(f"propagated_from:{from_agent}")
            new_entry.sentiment = dict(m.sentiment)
            new_entry.confidence = m.confidence

            if new_entry.hash not in self._hashes:
                self.memories.append(new_entry)
                self._hashes.add(new_entry.hash)
                count += 1

        self._audit("propagate", from_agent,
                    f"to={to_namespace} count={count}")
        return count

    # ── conflict resolution ─────────────────────────────────────────────

    def get_conflicts(self) -> List[Dict]:
        """Return unresolved conflicts."""
        return [c for c in self.conflicts if not c.get("resolved")]

    def resolve_conflict(self, conflict_index: int, resolution: str,
                         resolver: str = "system") -> bool:
        """Resolve a conflict by choosing which memory wins."""
        if conflict_index >= len(self.conflicts):
            return False
        conflict = self.conflicts[conflict_index]
        conflict["resolved"] = True
        conflict["resolution"] = resolution
        conflict["resolved_by"] = resolver
        conflict["resolved_at"] = datetime.now().isoformat()
        self._audit("resolve_conflict", resolver,
                    f"index={conflict_index} resolution={resolution}")
        return True

    # ── persistence ─────────────────────────────────────────────────────

    def save(self) -> str:
        """Save pool state to disk."""
        data = {
            "version": "0.3.0",
            "pool_name": self.pool_name,
            "saved_at": datetime.now().isoformat(),
            "agent_count": len(self.permissions),
            "memory_count": len(self.memories),
            "conflict_count": len(self.conflicts),
            "permissions": {k: v.to_dict()
                            for k, v in self.permissions.items()},
            "memories": [m.to_dict() for m in self.memories],
            "conflicts": self.conflicts,
        }
        with open(self.state_path, "w") as f:
            json.dump(data, f, indent=2)
        return self.state_path

    def load(self) -> int:
        """Load pool state from disk."""
        if not os.path.exists(self.state_path):
            return 0
        with open(self.state_path) as f:
            data = json.load(f)
        self.pool_name = data.get("pool_name", self.pool_name)
        self.permissions = {
            k: AgentPermission.from_dict(v)
            for k, v in data.get("permissions", {}).items()
        }
        self.memories = [MemoryEntry.from_dict(d)
                         for d in data.get("memories", [])]
        self._hashes = {m.hash for m in self.memories}
        self.conflicts = data.get("conflicts", [])
        return len(self.memories)

    # ── stats ───────────────────────────────────────────────────────────

    def stats(self) -> Dict:
        """Pool statistics."""
        namespaces = {}
        agents = {}
        for m in self.memories:
            ns = self._get_namespace(m)
            namespaces[ns] = namespaces.get(ns, 0) + 1
            agent = self._get_agent(m)
            if agent:
                agents[agent] = agents.get(agent, 0) + 1

        return {
            "pool_name": self.pool_name,
            "total_memories": len(self.memories),
            "registered_agents": len(self.permissions),
            "namespaces": namespaces,
            "memories_by_agent": agents,
            "unresolved_conflicts": len(self.get_conflicts()),
            "total_conflicts": len(self.conflicts),
        }

    # ── private ─────────────────────────────────────────────────────────

    def _check_admin(self, agent_id: str) -> bool:
        perm = self.permissions.get(agent_id)
        return perm and perm.can_admin()

    def _get_namespace(self, entry: MemoryEntry) -> str:
        for tag in entry.tags:
            if tag.startswith("ns:"):
                return tag[3:]
        return "shared"

    def _get_agent(self, entry: MemoryEntry) -> Optional[str]:
        for tag in entry.tags:
            if tag.startswith("agent:"):
                return tag[6:]
        return None

    def _check_conflict(self, new_entry: MemoryEntry,
                        agent_id: str) -> Optional[Dict]:
        """Check if new memory conflicts with existing ones from other agents."""
        import re
        new_words = set(re.findall(r"\w{4,}", new_entry.content.lower()))

        for existing in self.memories:
            existing_agent = self._get_agent(existing)
            if existing_agent == agent_id:
                continue  # Same agent, no conflict

            existing_words = set(
                re.findall(r"\w{4,}", existing.content.lower()))
            overlap = len(new_words & existing_words)

            if overlap < 3:
                continue

            # Check for negation patterns suggesting contradiction
            new_lower = new_entry.content.lower()
            exist_lower = existing.content.lower()
            negation_signals = [
                ("not ", ""), ("don't ", "do "), ("won't ", "will "),
                ("can't ", "can "), ("shouldn't ", "should "),
                ("reject", "accept"), ("disagree", "agree"),
                ("false", "true"), ("wrong", "right"),
                ("failed", "succeeded"), ("no ", "yes "),
            ]

            for neg, pos in negation_signals:
                if ((neg in new_lower and pos in exist_lower) or
                        (pos in new_lower and neg in exist_lower)):
                    return {
                        "type": "contradiction",
                        "new_memory": new_entry.hash,
                        "new_agent": agent_id,
                        "new_content": new_entry.content[:200],
                        "existing_memory": existing.hash,
                        "existing_agent": existing_agent,
                        "existing_content": existing.content[:200],
                        "overlap_words": list(new_words & existing_words)[:10],
                        "detected_at": datetime.now().isoformat(),
                        "resolved": False,
                    }
        return None

    def _audit(self, action: str, agent_id: str, detail: str = "") -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "agent_id": agent_id,
            "detail": detail,
        }
        log = []
        if os.path.exists(self.audit_path):
            try:
                with open(self.audit_path) as f:
                    log = json.load(f)
            except (json.JSONDecodeError, IOError):
                log = []
        log.append(entry)
        # Keep last 500 entries
        with open(self.audit_path, "w") as f:
            json.dump(log[-500:], f, indent=2)
