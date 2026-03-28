"""Conflict Resolver — resolves conflicts between agents."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("agents.conflict_resolver")


class ConflictResolver:
    def resolve(self, conflicts: list[dict[str, Any]], strategy: str = "priority") -> dict[str, Any]:
        if not conflicts:
            return {"resolution": None}
        if strategy == "priority":
            sorted_conflicts = sorted(conflicts, key=lambda c: c.get("priority", 0), reverse=True)
            winner = sorted_conflicts[0]
        else:
            winner = conflicts[0]
        logger.info("Resolved conflict using %s strategy", strategy)
        return {"resolution": winner, "strategy": strategy}
