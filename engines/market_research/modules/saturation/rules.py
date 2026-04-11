"""Saturation rules — hard constraints on market entry based on saturation."""
from __future__ import annotations

from typing import Any


RULES = [
    {
        "id": "max_saturation_block",
        "name": "Oversaturation blocker",
        "description": "Block entry if saturation index > 80 without sub-niche plan",
        "check": lambda data: data.get("saturation_index", 0) <= 80 or data.get("has_sub_niche_plan", False),
        "severity": "blocker",
        "action": "Market oversaturated — develop sub-niche strategy before entering",
    },
    {
        "id": "margin_floor",
        "name": "Minimum margin check",
        "description": "Avg category margin must be >15% for sustainable business",
        "check": lambda data: data.get("avg_margin", 50) >= 15,
        "severity": "blocker",
        "action": "Category margins too thin — cannot build profitable business",
    },
    {
        "id": "monopoly_warning",
        "name": "Monopoly detection",
        "description": "Warn if top 3 sellers control >70% of market",
        "check": lambda data: data.get("top3_concentration", 0) <= 70,
        "severity": "warning",
        "action": "Market dominated by few players — extremely hard to break in",
    },
    {
        "id": "rising_cpc_warning",
        "name": "Ad cost escalation",
        "description": "Warn if CPCs are rising >15% — competition for ads intensifying",
        "check": lambda data: data.get("cpc_trend", 0) <= 15,
        "severity": "warning",
        "action": "Ad costs escalating — organic/content strategy needed",
    },
    {
        "id": "price_war_detection",
        "name": "Price war detection",
        "description": "Detect if prices are in freefall (>10% decline)",
        "check": lambda data: data.get("price_trend_pct", 0) >= -10,
        "severity": "warning",
        "action": "Price war underway — margins being destroyed. Avoid or differentiate on value.",
    },
]


def evaluate_rules(saturation_data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all saturation rules."""
    blockers = []
    warnings = []

    for rule in RULES:
        try:
            passed = rule["check"](saturation_data)
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
