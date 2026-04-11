"""Emerging niches rules — constraints on niche entry decisions.

Guard rails to prevent chasing noise or over-investing in unproven niches.
"""
from __future__ import annotations
from typing import Any

from .data import SIGNAL_WEIGHTS


# Minimum number of distinct signal types required (search, social, funding, etc.)
MIN_SIGNAL_DIVERSITY = 2

# Maximum initial investment (USD) for an unproven niche
MAX_UNPROVEN_INVESTMENT = 500

# Validation must pass before scaling investment
SCALE_REQUIRES_VALIDATION = True

# Minimum combined signal score (weighted) to consider a niche worth investigating
MIN_WEIGHTED_SIGNAL_SCORE = 15.0

# Maximum percentage of inventory budget on a single unproven niche
MAX_INVENTORY_PCT_UNPROVEN = 0.10


RULES: list[dict[str, Any]] = [
    {
        "id": "min_signal_diversity",
        "name": "Minimum signal diversity",
        "description": "Need 2+ signal types with score > 0 to confirm niche is real",
        "severity": "blocker",
        "action": "Gather data from more signal sources before proceeding",
        "check": lambda niche: _count_active_signals(niche.get("signals", {})) >= MIN_SIGNAL_DIVERSITY,
    },
    {
        "id": "max_unproven_investment",
        "name": "Max investment for unproven niche",
        "description": f"Don't invest more than ${MAX_UNPROVEN_INVESTMENT} before validation",
        "severity": "blocker",
        "action": f"Cap initial spend at ${MAX_UNPROVEN_INVESTMENT}, validate first",
        "check": lambda niche: niche.get("proposed_investment", 0) <= MAX_UNPROVEN_INVESTMENT
                               or niche.get("validated", False),
    },
    {
        "id": "validation_before_scale",
        "name": "Validation required before scaling",
        "description": "Must complete validation playbook before investing > $500",
        "severity": "blocker",
        "action": "Run $200 validation test first (see knowledge.py playbook)",
        "check": lambda niche: niche.get("validated", False)
                               or niche.get("proposed_investment", 0) <= MAX_UNPROVEN_INVESTMENT,
    },
    {
        "id": "no_single_event_niches",
        "name": "Don't enter single-event niches",
        "description": "Niches driven by one news event are usually fads",
        "severity": "warning",
        "action": "Wait 4 weeks to see if signals persist beyond the initial event",
        "check": lambda niche: niche.get("trigger") != "viral_event"
                               or niche.get("signal_duration_weeks", 0) >= 4,
    },
    {
        "id": "min_weighted_score",
        "name": "Minimum weighted signal score",
        "description": f"Combined weighted score must exceed {MIN_WEIGHTED_SIGNAL_SCORE}",
        "severity": "warning",
        "action": "Signal too weak — monitor but don't invest yet",
        "check": lambda niche: _weighted_score(niche.get("signals", {})) >= MIN_WEIGHTED_SIGNAL_SCORE,
    },
    {
        "id": "not_mainstream_already",
        "name": "Not already mainstream",
        "description": "Don't enter niches already in mainstream stage",
        "severity": "warning",
        "action": "Too late for early-mover advantage — find a sub-niche instead",
        "check": lambda niche: niche.get("maturity") != "mainstream",
    },
    {
        "id": "inventory_cap",
        "name": "Inventory budget cap for unproven niche",
        "description": f"Max {MAX_INVENTORY_PCT_UNPROVEN * 100:.0f}% of inventory budget on unproven niche",
        "severity": "warning",
        "action": "Reduce order quantity — start with minimum viable inventory",
        "check": lambda niche: niche.get("maturity") in ("growing", "mainstream")
                               or niche.get("inventory_pct", 0) <= MAX_INVENTORY_PCT_UNPROVEN,
    },
]


def _count_active_signals(signals: dict[str, float]) -> int:
    """Count signal types with score > 0."""
    return sum(1 for v in signals.values() if v and v > 0)


def _weighted_score(signals: dict[str, float]) -> float:
    """Calculate weighted signal score using SIGNAL_WEIGHTS."""
    score = 0.0
    for signal_type, weight in SIGNAL_WEIGHTS.items():
        score += signals.get(signal_type, 0) * weight
    return round(score, 2)


def evaluate_niche_rules(niche_data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all rules against a niche candidate."""
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for rule in RULES:
        try:
            passed = rule["check"](niche_data)
        except Exception:
            passed = True

        if not passed:
            entry = {"rule_id": rule["id"], "name": rule["name"], "action": rule["action"]}
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
