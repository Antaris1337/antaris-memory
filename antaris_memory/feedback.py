"""
Retrieval Feedback Loop — Sprint 2.7

Records retrieval outcomes and applies them back to memory entries:

- ``"good"``    → boost importance (×1.2)
- ``"bad"``     → reduce importance (×0.8)
- ``"neutral"`` → no change

Feedback is persisted as newline-delimited JSON (``outcomes.jsonl``) in the
workspace directory so it survives process restarts.

Router integration: ``record_routing_outcome(model, outcome)`` writes a
routing-level event alongside retrieval events in the same file.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .entry import MemoryEntry

# Valid outcome values
OUTCOME_GOOD = "good"
OUTCOME_BAD = "bad"
OUTCOME_NEUTRAL = "neutral"
VALID_OUTCOMES = {OUTCOME_GOOD, OUTCOME_BAD, OUTCOME_NEUTRAL}

# Boost / penalty multipliers
GOOD_IMPORTANCE_MULT = 1.2   # multiply importance by this on good outcome
BAD_IMPORTANCE_MULT = 0.8    # multiply importance by this on bad outcome (lower = less likely to surface)


class RetrievalFeedback:
    """Tracks retrieval outcomes and mutates memory entries accordingly.

    Parameters
    ----------
    workspace : str
        Directory to store ``outcomes.jsonl``.  Typically the same
        workspace used by :class:`~antaris_memory.MemorySystemV4`.
    """

    def __init__(self, workspace: str) -> None:
        self.workspace = os.path.abspath(workspace)
        self._log_path = os.path.join(self.workspace, "outcomes.jsonl")

    # ── Public API ─────────────────────────────────────────────────────

    def record_outcome(
        self,
        memories: List["MemoryEntry"],
        memory_ids: List[str],
        outcome: str,
    ) -> int:
        """Apply *outcome* to the listed memory IDs and persist the event.

        Parameters
        ----------
        memories:
            The live in-memory list (``MemorySystemV4.memories``).
        memory_ids:
            IDs (hash values) of the entries that were retrieved.  These
            match ``MemoryEntry.hash`` which is also accessible as
            ``SearchResult.entry.hash``.
        outcome:
            ``"good"``, ``"bad"``, or ``"neutral"``.

        Returns
        -------
        int
            Number of entries that were found and mutated.
        """
        outcome = outcome.lower()
        if outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {sorted(VALID_OUTCOMES)}, got {outcome!r}"
            )

        id_set = set(memory_ids)
        mutated = 0

        for entry in memories:
            # Entries are identified by their ``hash`` field
            if entry.hash not in id_set:
                continue
            self._apply_to_entry(entry, outcome)
            mutated += 1

        self._append_log(
            event_type="retrieval",
            memory_ids=memory_ids,
            outcome=outcome,
            affected=mutated,
        )
        return mutated

    def record_routing_outcome(self, model: str, outcome: str) -> None:
        """Record a router-level outcome event (no memory mutation).

        This connects antaris-router's outcome tracking to the same JSONL
        log so a single file captures both retrieval and routing signals.

        Parameters
        ----------
        model:
            The model name used in the routing decision.
        outcome:
            ``"good"``, ``"bad"``, or ``"neutral"``.
        """
        outcome = outcome.lower()
        if outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {sorted(VALID_OUTCOMES)}, got {outcome!r}"
            )
        self._append_log(
            event_type="routing",
            model=model,
            outcome=outcome,
        )

    def load_history(self, limit: int = 1000) -> List[dict]:
        """Return the most recent *limit* feedback events from the JSONL log.

        Parameters
        ----------
        limit:
            Maximum number of records to return (most recent first).

        Returns
        -------
        list[dict]
            Each dict has at least ``ts``, ``event_type``, and ``outcome`` keys.
        """
        if not os.path.exists(self._log_path):
            return []
        lines: List[str] = []
        try:
            with open(self._log_path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            return []

        records = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(records))

    def stats(self) -> dict:
        """Return aggregate statistics from the feedback log.

        Returns
        -------
        dict
            Keys: ``total``, ``good``, ``bad``, ``neutral``, ``routing``, ``retrieval``.
        """
        history = self.load_history(limit=10_000)
        counts: dict = {
            "total": len(history),
            "good": 0,
            "bad": 0,
            "neutral": 0,
            "routing": 0,
            "retrieval": 0,
        }
        for rec in history:
            o = rec.get("outcome", "")
            if o in counts:
                counts[o] += 1
            t = rec.get("event_type", "")
            if t in ("routing", "retrieval"):
                counts[t] += 1
        return counts

    # ── Private helpers ────────────────────────────────────────────────

    @staticmethod
    def _apply_to_entry(entry: "MemoryEntry", outcome: str) -> None:
        """Mutate *entry* in-place based on *outcome*.

        ``importance`` is the per-entry scoring knob.  Decay half-life is
        a system-level setting on ``DecayEngine`` — there is no per-entry
        half-life to mutate.  Both outcomes adjust ``importance`` only:

        - ``good``    → multiply importance by ``GOOD_IMPORTANCE_MULT`` (1.2, capped at 1.0)
        - ``bad``     → multiply importance by ``BAD_IMPORTANCE_MULT`` (0.8, floor at 0.0)
        - ``neutral`` → no change
        """
        if outcome == OUTCOME_GOOD:
            entry.importance = min(1.0, entry.importance * GOOD_IMPORTANCE_MULT)
        elif outcome == OUTCOME_BAD:
            entry.importance = max(0.0, entry.importance * BAD_IMPORTANCE_MULT)
        # NEUTRAL: no change

    def _append_log(self, **kwargs) -> None:
        """Append a single JSON record to outcomes.jsonl."""
        record = {"ts": time.time(), **kwargs}
        os.makedirs(self.workspace, exist_ok=True)
        try:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError:
            pass  # non-fatal: feedback persistence is best-effort
