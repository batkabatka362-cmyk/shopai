"""ConflictResolver — detects and resolves contradictory agent recommendations."""

from __future__ import annotations

from datetime import datetime, timezone


class ConflictResolver:
    """Finds conflicts among agent results and resolves them with configurable strategies."""

    STRATEGIES = ("priority", "confidence", "merge", "vote")

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    @staticmethod
    def detect_conflicts(results: list[dict]) -> list[dict]:
        """Scan a list of result dicts for contradicting recommendations.

        Two results conflict when they cover the same ``field`` or ``key``
        but produce different values.  Each result should have at minimum:
        ``agent_id``, and either ``recommendation`` (a dict) or flat keys.

        Returns a list of conflict records.
        """
        if len(results) < 2:
            return []

        # Normalise: extract key-value recommendations from each result
        meta_keys = {"agent_id", "source", "confidence", "priority", "timestamp"}
        agent_recs: list[tuple[str, dict]] = []
        for r in results:
            agent_id = r.get("agent_id", r.get("source", "unknown"))
            rec = r.get("recommendation", {})
            if not rec:
                # Treat entire dict (minus meta keys) as the recommendation
                rec = {k: v for k, v in r.items() if k not in meta_keys}
            agent_recs.append((agent_id, rec))

        conflicts: list[dict] = []
        seen_pairs: set[tuple[str, str, str]] = set()

        for i in range(len(agent_recs)):
            aid_a, rec_a = agent_recs[i]
            for j in range(i + 1, len(agent_recs)):
                aid_b, rec_b = agent_recs[j]
                # Find shared keys with different values
                shared_keys = set(rec_a.keys()) & set(rec_b.keys())
                for key in shared_keys:
                    if rec_a[key] != rec_b[key]:
                        pair_key = (min(aid_a, aid_b), max(aid_a, aid_b), key)
                        if pair_key in seen_pairs:
                            continue
                        seen_pairs.add(pair_key)
                        conflicts.append({
                            "field": key,
                            "agents": [aid_a, aid_b],
                            "values": {aid_a: rec_a[key], aid_b: rec_b[key]},
                            "sources": [results[i], results[j]],
                            "detected_at": datetime.now(timezone.utc).isoformat(),
                        })

        return conflicts

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(
        self, conflicts: list[dict], strategy: str = "priority", votes: dict | None = None
    ) -> list[dict]:
        """Resolve a list of conflicts using the chosen strategy.

        Returns a list of resolution dicts with the winning value for each conflict.
        """
        if strategy not in self.STRATEGIES:
            raise ValueError(f"Unknown strategy '{strategy}'. Must be one of {self.STRATEGIES}")

        resolutions: list[dict] = []
        for conflict in conflicts:
            if strategy == "priority":
                res = self._resolve_by_priority(conflict)
            elif strategy == "confidence":
                res = self._resolve_by_confidence(conflict)
            elif strategy == "merge":
                res = self._resolve_by_merge(conflict)
            elif strategy == "vote":
                res = self._resolve_by_vote(conflict, votes or {})
            else:
                raise ValueError(f"Unsupported strategy: {strategy}")
            resolutions.append(res)

        return resolutions

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_by_priority(conflict: dict) -> dict:
        """Pick the value from the agent with the highest priority (lowest number = best)."""
        sources = conflict.get("sources", [])
        if not sources:
            return {"field": conflict["field"], "resolved_value": None, "method": "priority"}

        best_source = min(
            sources,
            key=lambda s: s.get("priority", 999),
        )
        agent_id = best_source.get("agent_id", best_source.get("source", "unknown"))
        resolved_value = conflict["values"].get(agent_id)

        # Fallback: if agent_id not in values, take the first available value
        if resolved_value is None and conflict["values"]:
            resolved_value = next(iter(conflict["values"].values()))

        return {
            "field": conflict["field"],
            "resolved_value": resolved_value,
            "chosen_agent": agent_id,
            "method": "priority",
        }

    @staticmethod
    def _resolve_by_confidence(conflict: dict) -> dict:
        """Pick the value from the agent with the highest confidence score."""
        sources = conflict.get("sources", [])
        if not sources:
            return {"field": conflict["field"], "resolved_value": None, "method": "confidence"}

        best_source = max(
            sources,
            key=lambda s: s.get("confidence", 0.0),
        )
        agent_id = best_source.get("agent_id", best_source.get("source", "unknown"))
        resolved_value = conflict["values"].get(agent_id)

        if resolved_value is None and conflict["values"]:
            resolved_value = next(iter(conflict["values"].values()))

        return {
            "field": conflict["field"],
            "resolved_value": resolved_value,
            "chosen_agent": agent_id,
            "method": "confidence",
            "confidence": best_source.get("confidence", 0.0),
        }

    @staticmethod
    def _resolve_by_merge(conflict: dict) -> dict:
        """Attempt to merge non-conflicting parts of the values.

        If both values are dicts, combine their keys (agent B overrides A on overlap).
        If both are lists, concatenate and deduplicate by content.
        Otherwise fall back to the first agent's value.
        """
        agents = conflict.get("agents", [])
        values = conflict.get("values", {})
        val_list = [values.get(a) for a in agents]

        if len(val_list) < 2:
            merged = val_list[0] if val_list else None
        elif isinstance(val_list[0], dict) and isinstance(val_list[1], dict):
            merged = {**val_list[0], **val_list[1]}
        elif isinstance(val_list[0], list) and isinstance(val_list[1], list):
            # Dedupe by CONTENT, not id(). The previous version used
            # `id(item)` for unhashable types, which only matched if
            # the SAME object reference appeared in both lists — two
            # equivalent dicts in the two source lists would NOT
            # dedupe because they had different ids. Now we serialize
            # via repr() as a stable content key.
            seen: set[str] = set()
            merged = []
            for item in val_list[0] + val_list[1]:
                if isinstance(item, (str, int, float, bool, type(None))):
                    key = f"primitive:{type(item).__name__}:{item!r}"
                else:
                    try:
                        key = f"hashable:{hash(item)}"
                    except TypeError:
                        # Unhashable (dict, list, set) — fall back to
                        # repr() which gives a stable content key.
                        key = f"repr:{repr(item)}"
                if key not in seen:
                    seen.add(key)
                    merged.append(item)
        else:
            # Non-mergeable types — pick first
            merged = val_list[0]

        return {
            "field": conflict.get("field"),
            "resolved_value": merged,
            "method": "merge",
        }

    @staticmethod
    def _resolve_by_vote(conflict: dict, votes: dict) -> dict:
        """Resolve by external vote counts.

        ``votes`` maps agent_id -> vote count (int).  The agent with the
        most votes wins.
        """
        agents = conflict.get("agents", [])
        values = conflict.get("values", {})

        if not votes:
            # No votes provided — pick first agent
            winner = agents[0] if agents else None
        else:
            relevant = {a: votes.get(a, 0) for a in agents}
            winner = max(relevant, key=relevant.get) if relevant else None  # type: ignore[arg-type]

        resolved_value = values.get(winner) if winner else None

        return {
            "field": conflict["field"],
            "resolved_value": resolved_value,
            "chosen_agent": winner,
            "method": "vote",
            "vote_counts": {a: votes.get(a, 0) for a in agents},
        }
