"""Differentiation rules — constraints on valid differentiation strategies.

Core principles:
  - Differentiation must be DEFENSIBLE (not easily copied within months)
  - Differentiation must be VALUED by customers (not different for its own sake)
  - Differentiation must be COMMUNICABLE in a single sentence
"""
from __future__ import annotations

from typing import Any


# Minimum months a strategy must be defensible to be worth pursuing
DEFENSIBILITY_MINIMUM_MONTHS = 6

# Minimum percentage of target customers who must care about the differentiator
CUSTOMER_VALUE_THRESHOLD = 30

# Maximum words allowed for a differentiation statement
MAX_STATEMENT_WORDS = 15


RULES = [
    {
        "id": "must_be_defensible",
        "name": "Defensibility requirement",
        "description": (
            "Strategy must remain defensible for at least "
            f"{DEFENSIBILITY_MINIMUM_MONTHS} months before competitors can copy"
        ),
        "check": lambda s: s.get("sustainability", {}).get(
            "months_defensible", 0
        ) >= DEFENSIBILITY_MINIMUM_MONTHS,
        "severity": "blocker",
        "action": "Strategy too easy to copy — choose a more defensible approach",
    },
    {
        "id": "must_be_customer_valued",
        "name": "Customer value requirement",
        "description": (
            "Differentiation must matter to customers, not just be different "
            "for the sake of being different"
        ),
        "check": lambda s: s.get("customer_value_pct", 100) >= CUSTOMER_VALUE_THRESHOLD,
        "severity": "blocker",
        "action": (
            "Customers don't value this differentiator enough — "
            "find something they actually care about"
        ),
    },
    {
        "id": "must_be_communicable",
        "name": "One-sentence communicability",
        "description": (
            f"Must be expressible in {MAX_STATEMENT_WORDS} words or fewer. "
            "If you can't explain it simply, customers won't get it."
        ),
        "check": lambda s: len(
            s.get("differentiation_statement", "x " * 20).split()
        ) <= MAX_STATEMENT_WORDS,
        "severity": "warning",
        "action": "Simplify the differentiation message — too complex for customers",
    },
    {
        "id": "budget_must_cover_cost",
        "name": "Budget feasibility",
        "description": "Implementation cost must be within available budget",
        "check": lambda s: _budget_covers_cost(
            s.get("budget", "medium"), s.get("cost_level", "medium")
        ),
        "severity": "blocker",
        "action": "Insufficient budget for this strategy — choose a lower-cost option",
    },
    {
        "id": "no_feature_only_differentiation",
        "name": "Feature-only trap avoidance",
        "description": (
            "Pure feature differentiation is the easiest to copy. "
            "Must combine with at least one other dimension."
        ),
        "check": lambda s: s.get("strategy_type") != "features_only",
        "severity": "warning",
        "action": (
            "Feature-only differentiation is easily copied — "
            "layer in brand, service, or content differentiation"
        ),
    },
    {
        "id": "timeline_must_be_realistic",
        "name": "Timeline realism",
        "description": "Implementation time must fit within the given timeline",
        "check": lambda s: s.get("cost_estimate", {}).get(
            "time_months", 0
        ) <= s.get("timeline_months", 12),
        "severity": "warning",
        "action": "Strategy takes longer than available timeline — adjust scope or timeline",
    },
]


def evaluate_rules(
    strategy: dict[str, Any], context: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Evaluate all differentiation rules against a proposed strategy.

    Args:
        strategy: Strategy dict with keys like sustainability, cost_level, etc.
        context: Optional additional context (budget, timeline, etc.)

    Returns:
        Dict with passed (bool), blockers, warnings, and rules_evaluated count.
    """
    merged = {**strategy, **(context or {})}
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for rule in RULES:
        try:
            passed = rule["check"](merged)
        except Exception:
            # If rule cannot be evaluated, assume pass (missing data)
            passed = True

        if not passed:
            entry = {
                "rule_id": rule["id"],
                "name": rule["name"],
                "description": rule["description"],
                "action": rule["action"],
            }
            if rule["severity"] == "blocker":
                blockers.append(entry)
            else:
                warnings.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "rules_evaluated": len(RULES),
    }


def _budget_covers_cost(budget: str, cost_level: str) -> bool:
    """Check if the budget tier can cover the cost tier."""
    tiers = {"low": 1, "medium": 2, "high": 3}
    return tiers.get(budget, 2) >= tiers.get(cost_level, 2)
