"""Search volume rules — hard constraints for viable product demand.

Rules that MUST pass before declaring a keyword/product viable:
  - Minimum 200 monthly searches for any viable product keyword
  - Transactional intent required for at least one primary keyword
  - Search volume must show stability (not a single-month spike)

Violations produce blockers (hard reject) or warnings (proceed with caution).
"""
from __future__ import annotations

from typing import Any


RULES = [
    {
        "id": "min_search_volume",
        "name": "Minimum monthly search volume",
        "description": "Aggregated monthly search volume must be at least 200 for viable demand",
        "check": lambda data: data.get("aggregate_volume", 0) >= 200,
        "severity": "blocker",
        "action": "Reject — insufficient search demand to sustain a product",
    },
    {
        "id": "transactional_intent_required",
        "name": "Transactional intent present",
        "description": (
            "At least one keyword must have transactional or commercial intent. "
            "Pure informational keywords do not convert to purchases."
        ),
        "check": lambda data: any(
            kw.get("intent") in ("transactional", "commercial")
            for kw in data.get("keywords", [])
        ),
        "severity": "blocker",
        "action": "Reject — no purchase-intent keywords found",
    },
    {
        "id": "volume_stability",
        "name": "Search volume stability check",
        "description": (
            "Coefficient of variation across months must be below 1.5. "
            "Spikes indicate viral moments, not sustained demand."
        ),
        "check": lambda data: data.get("volume_cv", 0) < 1.5,
        "severity": "blocker",
        "action": "Reject — volume is a temporary spike. Wait 3 months and re-evaluate.",
    },
    {
        "id": "not_declining_trend",
        "name": "Search trend not in decline",
        "description": "Volume should not be declining for 3+ consecutive months",
        "check": lambda data: data.get("consecutive_decline_months", 0) < 3,
        "severity": "warning",
        "action": "Caution — search volume declining. Demand may be shrinking.",
    },
    {
        "id": "min_keyword_count",
        "name": "Keyword diversity",
        "description": "At least 3 related keywords should have volume >= 50",
        "check": lambda data: len([
            kw for kw in data.get("keywords", []) if kw.get("volume", 0) >= 50
        ]) >= 3,
        "severity": "warning",
        "action": "Caution — demand concentrated in too few keywords. Expand research.",
    },
    {
        "id": "volume_not_inflated_seasonal",
        "name": "Seasonal inflation check",
        "description": "Raw volume may overstate demand during Nov/Dec peaks",
        "check": lambda data: data.get("seasonal_adjusted", False) is True,
        "severity": "info",
        "action": "Volume not seasonally adjusted — peak months inflate estimates 25-35%.",
    },
    {
        "id": "conversion_rate_sanity",
        "name": "Conversion rate plausibility",
        "description": "Estimated conversion rate must be between 0.1% and 15%",
        "check": lambda data: 0.001 <= data.get("estimated_conversion", 0.02) <= 0.15,
        "severity": "warning",
        "action": "Conversion rate outside normal range — verify data and category.",
    },
]


def evaluate_rules(analysis_data: dict[str, Any]) -> dict[str, Any]:
    """Run all search volume rules against analysis data.

    Returns:
        {"passed": bool, "blockers": [...], "warnings": [...], "info": [...],
         "rules_evaluated": int}
    """
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    info: list[dict[str, str]] = []

    for rule in RULES:
        try:
            passed = rule["check"](analysis_data)
        except Exception:
            passed = True  # Do not block on rule evaluation errors

        if not passed:
            entry = {
                "rule_id": rule["id"], "name": rule["name"],
                "description": rule["description"], "action": rule["action"],
            }
            bucket = (
                blockers if rule["severity"] == "blocker"
                else warnings if rule["severity"] == "warning"
                else info
            )
            bucket.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(RULES),
    }
