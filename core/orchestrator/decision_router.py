from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("orchestrator.decision_router")


class DecisionRouter:
    """Makes routing decisions based on context, priorities, and system state."""

    def __init__(self) -> None:
        self._priority_overrides: dict[str, int] = {}
        self._rules: list[dict[str, Any]] = []

    def add_rule(self, name: str, condition: dict[str, Any], action: str, priority: int = 0) -> None:
        self._rules.append({
            "name": name,
            "condition": condition,
            "action": action,
            "priority": priority,
        })
        self._rules.sort(key=lambda r: r["priority"], reverse=True)
        logger.info("Added decision rule: %s (priority=%d)", name, priority)

    def set_priority_override(self, engine_name: str, priority: int) -> None:
        self._priority_overrides[engine_name] = priority

    def evaluate(self, context: dict[str, Any]) -> str | None:
        for rule in self._rules:
            if self._matches(rule["condition"], context):
                logger.info("Decision rule '%s' matched", rule["name"])
                return rule["action"]
        logger.info("No decision rules matched for context")
        return None

    def select_engine(self, candidates: list[str]) -> str | None:
        if not candidates:
            return None
        scored = []
        for engine in candidates:
            priority = self._priority_overrides.get(engine, 0)
            scored.append((priority, engine))
        scored.sort(reverse=True)
        return scored[0][1]

    @staticmethod
    def _matches(condition: dict[str, Any], context: dict[str, Any]) -> bool:
        for key, expected in condition.items():
            if context.get(key) != expected:
                return False
        return True

    def list_rules(self) -> list[dict[str, Any]]:
        return list(self._rules)
