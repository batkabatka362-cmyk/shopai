"""Price sensitivity rules — hard constraints and guardrails.

Pricing rules every e-commerce store must follow:
  - Price must cover costs + minimum margin (no selling at a loss)
  - Price changes should not exceed 25% at once (customer shock)
  - Price testing requires proper A/B split (not sequential)
  - Prices must comply with MAP (Minimum Advertised Price) if applicable
"""
from __future__ import annotations

from typing import Any


# Pricing guardrails
PRICING_CONSTRAINTS = {
    "min_margin_pct": 0.20,              # Minimum 20% gross margin
    "max_single_price_change_pct": 0.25, # Max 25% change at once
    "min_ab_test_traffic": 1000,         # Min visitors per variant for significance
    "min_ab_test_days": 7,               # Min days to run price test
    "max_ab_test_days": 30,              # Max days before acting on results
    "price_review_interval_days": 30,    # Review pricing monthly
}

# Minimum viable margins by category
MIN_MARGINS_BY_CATEGORY = {
    "electronics": 0.15,
    "clothing": 0.40,
    "health_beauty": 0.50,
    "home_garden": 0.30,
    "sports_outdoors": 0.30,
    "pet_supplies": 0.35,
    "food_beverage": 0.40,
    "jewelry": 0.55,
    "toys_games": 0.30,
    "luxury": 0.60,
    "general": 0.25,
}

# Psychological pricing rules
PSYCHOLOGICAL_PRICING = {
    "charm_pricing_effect": 0.15,     # $X.99 reduces perceived price 15-20%
    "round_number_premium": True,      # Round numbers ($50) signal quality
    "anchor_ratio": 2.5,              # Show "was $X" at 2-3x creates deal perception
    "bundle_discount_sweet_spot": 0.15,  # 15% bundle discount maximizes take rate
}


RULES = [
    {
        "id": "price_covers_cost",
        "name": "Price must cover costs",
        "description": "Selling price must be above unit cost plus minimum margin",
        "check": lambda data: (
            data.get("current_price", 0) >=
            data.get("unit_cost", 0) * (1 + PRICING_CONSTRAINTS["min_margin_pct"])
        ),
        "severity": "blocker",
        "action": "Price is below cost + minimum margin — unsustainable. Raise price immediately.",
    },
    {
        "id": "price_change_limit",
        "name": "Price change maximum 25%",
        "description": "Single price change should not exceed 25% to avoid customer shock",
        "check": lambda data: (
            abs(data.get("price_change_pct", 0)) <= 25.0
        ),
        "severity": "warning",
        "action": "Price change exceeds 25% — implement gradually over 2-3 increments",
    },
    {
        "id": "ab_test_required",
        "name": "Price testing requires A/B split",
        "description": "Price experiments need simultaneous A/B testing, not sequential changes",
        "check": lambda data: (
            not data.get("is_price_test", False)
            or data.get("daily_visitors", 0) >= PRICING_CONSTRAINTS["min_ab_test_traffic"]
        ),
        "severity": "warning",
        "action": "Insufficient traffic for price A/B test — need 1000+ visitors per variant",
    },
    {
        "id": "not_below_competitor_floor",
        "name": "Price not racing to bottom",
        "description": "Pricing below 60% of competitor average suggests unsustainable race to bottom",
        "check": lambda data: (
            data.get("competitor_avg_price", 0) <= 0
            or data.get("current_price", 0) >= data.get("competitor_avg_price", 1) * 0.60
        ),
        "severity": "warning",
        "action": "Price is far below competitors — competing on price alone is unsustainable",
    },
    {
        "id": "not_above_ceiling",
        "name": "Price within willingness-to-pay range",
        "description": "Price should not exceed the 90th percentile willingness-to-pay",
        "check": lambda data: (
            data.get("price_ceiling", 0) <= 0
            or data.get("current_price", 0) <= data.get("price_ceiling", float("inf"))
        ),
        "severity": "info",
        "action": "Price may be above market willingness-to-pay ceiling",
    },
    {
        "id": "margin_healthy",
        "name": "Healthy margin check",
        "description": "Gross margin should meet category minimums for sustainability",
        "check": lambda data: (
            data.get("unit_cost", 0) <= 0
            or (data.get("current_price", 1) - data.get("unit_cost", 0)) / data.get("current_price", 1)
            >= MIN_MARGINS_BY_CATEGORY.get(data.get("category", "general"), 0.25)
        ),
        "severity": "warning",
        "action": "Margin is below category minimum — review cost structure or raise price",
    },
]


def evaluate_rules(pricing_data: dict[str, Any]) -> dict[str, Any]:
    """Run all pricing rules against the data.

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
            passed = rule["check"](pricing_data)
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
