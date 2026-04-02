"""Market risk rules — hard constraints and blockers.

Critical rules that MUST be checked before entering a market.
Violations = automatic rejection or mandatory warning.

Key blockers:
  - Saturation >80 = don't enter
  - Declining demand >20% = don't enter
  - <5 competitors but no search volume = no market exists
"""
from __future__ import annotations

from typing import Any


RULES = [
    {
        "id": "saturation_blocker",
        "name": "Market saturation too high",
        "description": (
            "Saturation score >80 means the market is overcrowded. "
            "New entrants face brutal competition and margin compression."
        ),
        "check": lambda data: data.get("dimensions", {})
            .get("saturation_level", {}).get("score", 0) <= 80,
        "severity": "blocker",
        "action": "Do NOT enter — market is oversaturated. Find a less crowded niche.",
    },
    {
        "id": "demand_decline_blocker",
        "name": "Demand declining too fast",
        "description": (
            "Demand trend score >85 (roughly -20%+ YoY decline) signals a dying market. "
            "You'll be fighting over a shrinking pie."
        ),
        "check": lambda data: data.get("dimensions", {})
            .get("demand_trend_direction", {}).get("score", 0) <= 85,
        "severity": "blocker",
        "action": "Do NOT enter — demand is falling off a cliff. Pivot to a growing market.",
    },
    {
        "id": "no_market_exists",
        "name": "No real market exists",
        "description": (
            "Few competitors AND no search volume means the market does not exist. "
            "Don't confuse 'untapped' with 'nonexistent'."
        ),
        "check": lambda data: not (
            data.get("input", {}).get("competitor_count", 50) < 5
            and data.get("input", {}).get("search_volume_trend_pct", 0) <= 0
        ),
        "severity": "blocker",
        "action": "No market detected — <5 competitors with no search demand. Validate demand first.",
    },
    {
        "id": "death_spiral_warning",
        "name": "Death spiral risk",
        "description": (
            "Rising competition + falling prices signals a race to the bottom. "
            "Margins will be squeezed until only the strongest survive."
        ),
        "check": lambda data: not (
            data.get("dimensions", {}).get("saturation_level", {}).get("score", 0) > 60
            and data.get("dimensions", {}).get("price_erosion_rate", {}).get("score", 0) > 50
        ),
        "severity": "warning",
        "action": "Death spiral risk — high saturation + falling prices. Only enter with strong differentiation.",
    },
    {
        "id": "composite_critical",
        "name": "Composite risk in critical zone",
        "description": (
            "Overall market risk score >75 signals danger across multiple dimensions. "
            "This is not a single fixable problem — the whole market is hostile."
        ),
        "check": lambda data: data.get("composite_score", 0) <= 75,
        "severity": "warning",
        "action": "Multiple risk factors are elevated — reconsider market selection.",
    },
    {
        "id": "price_erosion_severe",
        "name": "Severe price erosion",
        "description": (
            "Price erosion score >70 means prices are dropping fast. "
            "Your margins will shrink every quarter."
        ),
        "check": lambda data: data.get("dimensions", {})
            .get("price_erosion_rate", {}).get("score", 0) <= 70,
        "severity": "warning",
        "action": "Prices declining rapidly — must have cost advantage or premium positioning.",
    },
]


def evaluate_rules(
    assessment_data: dict[str, Any],
    input_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all market risk rules against the assessment.

    Args:
        assessment_data: Output from code.assess_market_risk()["data"]
        input_payload: Original input payload (for rules that check raw input)

    Returns:
        {passed, blockers, warnings, info, rules_evaluated}
    """
    # Merge input payload into assessment for rules that need raw inputs
    check_data = dict(assessment_data)
    if input_payload:
        check_data["input"] = input_payload

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []

    for rule in RULES:
        try:
            passed = rule["check"](check_data)
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
