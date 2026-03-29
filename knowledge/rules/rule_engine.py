"""Rule Engine -- business rule definitions and evaluation."""
from __future__ import annotations

import re
from typing import Any


class RuleEngine:
    """Declarative rule engine supporting condition matching and action execution."""

    def __init__(self) -> None:
        self._rules: dict[str, dict[str, Any]] = {}

    # ---- CRUD ----------------------------------------------------------

    def add_rule(
        self,
        rule_id: str,
        condition: dict,
        action: dict,
        priority: int = 0,
    ) -> None:
        """Register a rule.

        Args:
            rule_id: Unique identifier for the rule.
            condition: Dict of field -> {operator: value} pairs.
            action: Dict describing what to do when rule fires.
            priority: Higher priority rules evaluate first.
        """
        self._rules[rule_id] = {
            "rule_id": rule_id,
            "condition": condition,
            "action": action,
            "priority": priority,
        }

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def list_rules(self) -> list[dict]:
        rules = list(self._rules.values())
        rules.sort(key=lambda r: r["priority"], reverse=True)
        return rules

    # ---- Evaluation ----------------------------------------------------

    def evaluate(self, context: dict) -> list[dict]:
        """Evaluate all rules against *context* and return triggered rules
        sorted by descending priority."""
        triggered: list[dict] = []
        for rule in self.list_rules():
            if self.evaluate_rule(rule, context):
                triggered.append(rule)
        return triggered

    def evaluate_rule(self, rule: dict, context: dict) -> bool:
        """Return True when every condition clause matches *context*.

        Supports two condition formats:
          1. Nested: {"price": {"gt": 100}, "name": "exact_match"}
          2. Flat:   {"field": "price", "op": "gt", "value": 100}
        """
        condition = rule.get("condition", {})

        # Flat format: {"field": ..., "op": ..., "value": ...}
        if "field" in condition and "op" in condition:
            field = condition["field"]
            ctx_value = context.get(field)
            return self._check_operator(condition["op"], ctx_value, condition.get("value"))

        # Nested format: {field: {operator: expected}, ...}
        for field, checks in condition.items():
            value = context.get(field)
            if not isinstance(checks, dict):
                # Shorthand: field: expected_value  ->  eq
                if value != checks:
                    return False
                continue
            for operator, expected in checks.items():
                if not self._check_operator(operator, value, expected):
                    return False
        return True

    # ---- Action execution ----------------------------------------------

    def execute_actions(
        self, triggered_rules: list[dict], context: dict
    ) -> list[dict]:
        """Execute actions for *triggered_rules*, mutating/extending *context*.

        Returns a list of result dicts (one per rule) with keys
        ``rule_id``, ``action_type``, ``success``, and optional ``detail``.
        """
        results: list[dict] = []
        for rule in triggered_rules:
            action = rule.get("action", {})
            action_type = action.get("type", "unknown")
            result = {"rule_id": rule["rule_id"], "action_type": action_type, "success": True}
            try:
                self._apply_action(action, context)
            except Exception as exc:  # noqa: BLE001
                result["success"] = False
                result["detail"] = str(exc)
            results.append(result)
        return results

    # ---- Private helpers -----------------------------------------------

    _OPERATORS = {
        "eq", "ne", "gt", "lt", "gte", "lte",
        "in", "not_in", "contains", "regex",
    }

    @staticmethod
    def _check_operator(operator: str, value: Any, expected: Any) -> bool:
        if operator == "eq":
            return value == expected
        if operator == "ne":
            return value != expected
        if operator == "gt":
            return value is not None and value > expected
        if operator == "lt":
            return value is not None and value < expected
        if operator == "gte":
            return value is not None and value >= expected
        if operator == "lte":
            return value is not None and value <= expected
        if operator == "in":
            return value in expected
        if operator == "not_in":
            return value not in expected
        if operator == "contains":
            if isinstance(value, str):
                return expected in value
            if isinstance(value, (list, tuple, set)):
                return expected in value
            return False
        if operator == "regex":
            if value is None:
                return False
            return bool(re.search(expected, str(value)))
        raise ValueError(f"Unknown operator: {operator}")

    @staticmethod
    def _apply_action(action: dict, context: dict) -> None:
        action_type = action.get("type")
        field = action.get("field", "")
        act_value = action.get("value")

        if action_type == "set_field":
            context[field] = act_value
        elif action_type == "append":
            lst = context.setdefault(field, [])
            if not isinstance(lst, list):
                raise TypeError(f"Cannot append to non-list field '{field}'")
            lst.append(act_value)
        elif action_type == "remove":
            context.pop(field, None)
        elif action_type == "multiply":
            if field not in context:
                raise KeyError(f"Field '{field}' not in context for multiply")
            context[field] = context[field] * act_value
        elif action_type == "notify":
            # Notifications are stored in a special key for downstream consumers.
            notifications = context.setdefault("_notifications", [])
            notifications.append({"message": act_value, "field": field})
        else:
            raise ValueError(f"Unknown action type: {action_type}")
