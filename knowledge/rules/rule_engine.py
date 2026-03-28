"""Rule Engine — business rule definitions and evaluation."""
from __future__ import annotations
from typing import Any, Callable
from utils.logger import get_logger

logger = get_logger("knowledge.rules")


class RuleEngine:
    def __init__(self) -> None:
        self._rules: list[dict[str, Any]] = []

    def add_rule(self, name: str, condition: Callable[[dict], bool], action: str, priority: int = 0) -> None:
        self._rules.append({"name": name, "condition": condition, "action": action, "priority": priority})
        self._rules.sort(key=lambda r: r["priority"], reverse=True)

    def evaluate(self, data: dict[str, Any]) -> list[str]:
        actions = []
        for rule in self._rules:
            if rule["condition"](data):
                actions.append(rule["action"])
                logger.info("Rule '%s' triggered", rule["name"])
        return actions

    def list_rules(self) -> list[str]:
        return [r["name"] for r in self._rules]
