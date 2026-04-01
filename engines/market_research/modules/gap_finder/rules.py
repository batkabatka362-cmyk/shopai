"""Gap finder rules — constraints on gap pursuit decisions.

Prevents chasing unprofitable gaps or overextending resources.
"""
from __future__ import annotations

from typing import Any


RULES = [
    {
        "id": "min_opportunity_score",
        "name": "Minimum opportunity threshold",
        "description": "Don't pursue gaps with opportunity score below 35",
        "check": lambda gap: gap.get("opportunity_score", 0) >= 35,
        "severity": "blocker",
        "action": "Gap too weak to pursue — wait for better opportunities",
    },
    {
        "id": "max_simultaneous_gaps",
        "name": "Focus limit",
        "description": "Don't pursue more than 3 gaps simultaneously",
        "check": lambda ctx: ctx.get("currently_pursuing", 0) < 3,
        "severity": "warning",
        "action": "Already pursuing maximum gaps — finish current before starting new",
    },
    {
        "id": "gap_must_be_actionable",
        "name": "Actionability check",
        "description": "Gap must have clear actionable path",
        "check": lambda gap: gap.get("actionable", False),
        "severity": "warning",
        "action": "Gap identified but no clear action path — research more",
    },
    {
        "id": "no_regulated_without_compliance",
        "name": "Compliance gate",
        "description": "Don't pursue gaps in regulated categories without compliance plan",
        "check": lambda ctx: not ctx.get("regulated_category", False) or ctx.get("compliance_ready", False),
        "severity": "blocker",
        "action": "Category is regulated — complete compliance plan before pursuing",
    },
    {
        "id": "budget_matches_gap",
        "name": "Budget feasibility",
        "description": "Estimated cost to fill gap must be within budget",
        "check": lambda ctx: ctx.get("estimated_cost", 0) <= ctx.get("available_budget", float("inf")),
        "severity": "blocker",
        "action": "Insufficient budget to fill this gap",
    },
]


def evaluate_rules(gap: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate gap pursuit rules."""
    ctx = {**gap, **(context or {})}
    blockers = []
    warnings = []

    for rule in RULES:
        try:
            passed = rule["check"](ctx)
        except Exception:
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
