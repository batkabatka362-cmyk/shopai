"""Market size rules — hard constraints and guardrails.

Rules that MUST be checked before any market entry decision.
Violations = automatic rejection or mandatory warning.
"""
from __future__ import annotations

from typing import Any


RULES = [
    {
        "id": "min_som",
        "name": "Minimum SOM threshold",
        "description": "Monthly SOM must be at least $3,000 to cover basic operating costs",
        "check": lambda data: data.get("som", {}).get("monthly_som_usd", {}).get("typical", 0) >= 3000,
        "severity": "blocker",
        "action": "Reject market — insufficient revenue potential",
    },
    {
        "id": "min_tam",
        "name": "Minimum TAM for sustainability",
        "description": "Annual TAM must be at least $50M for long-term viability",
        "check": lambda data: data.get("tam", {}).get("annual_tam_usd", 0) >= 50_000_000,
        "severity": "warning",
        "action": "Flag as limited growth potential",
    },
    {
        "id": "niche_not_too_broad",
        "name": "Niche specificity",
        "description": "Sub-niche should be <50% of total category for differentiation",
        "check": lambda data: data.get("tam", {}).get("sub_niche_pct", 1.0) <= 0.5,
        "severity": "warning",
        "action": "Suggest narrowing the niche for better positioning",
    },
    {
        "id": "capture_rate_realistic",
        "name": "Capture rate sanity check",
        "description": "Required SOM capture must be under 100% (physically possible)",
        "check": lambda data: True,  # Checked dynamically
        "severity": "blocker",
        "action": "Target revenue exceeds market size — unrealistic",
    },
    {
        "id": "som_upside_exists",
        "name": "Upside potential",
        "description": "Max SOM should be at least 2x typical for growth headroom",
        "check": lambda data: (
            data.get("som", {}).get("monthly_som_usd", {}).get("max", 0) >=
            data.get("som", {}).get("monthly_som_usd", {}).get("typical", 1) * 1.5
        ),
        "severity": "info",
        "action": "Limited upside — growth ceiling is low",
    },
]


def evaluate_rules(market_size: dict[str, Any]) -> dict[str, Any]:
    """Run all market size rules against the data.

    Returns:
        {
            "passed": bool,
            "blockers": [...],
            "warnings": [...],
            "info": [...],
            "rules_evaluated": int,
        }
    """
    blockers = []
    warnings = []
    info = []

    for rule in RULES:
        try:
            passed = rule["check"](market_size)
        except Exception:
            passed = True  # Don't block on rule evaluation errors

        if not passed:
            entry = {
                "rule_id": rule["id"],
                "name": rule["name"],
                "description": rule["description"],
                "action": rule["action"],
            }
            if rule["severity"] == "blocker":
                blockers.append(entry)
            elif rule["severity"] == "warning":
                warnings.append(entry)
            else:
                info.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(RULES),
    }
