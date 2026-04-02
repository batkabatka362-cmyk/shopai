"""Conversion rules — hard constraints and realistic bounds.

Realistic conversion benchmarks based on traffic temperature:
  - Cold traffic (paid ads to strangers): 0.5% - 5%
  - Warm traffic (retargeting, social followers): 3% - 10%
  - Hot traffic (email list, repeat customers): 5% - 25%

Cart abandonment benchmarks:
  - Global average: ~70%
  - Mobile: ~78%
  - Desktop: ~63%
  - Best-in-class: ~55%
"""
from __future__ import annotations

from typing import Any


# Conversion rate bounds by traffic temperature
CONVERSION_BOUNDS = {
    "cold": {"min": 0.005, "max": 0.05, "typical": 0.02},
    "warm": {"min": 0.03, "max": 0.10, "typical": 0.06},
    "hot": {"min": 0.05, "max": 0.15, "typical": 0.10},
    "email": {"min": 0.03, "max": 0.15, "typical": 0.08},
    "repeat_customer": {"min": 0.10, "max": 0.25, "typical": 0.18},
}

# Cart abandonment rate benchmarks
CART_ABANDONMENT_BENCHMARKS = {
    "global_average": 0.70,
    "mobile": 0.78,
    "desktop": 0.63,
    "best_in_class": 0.55,
    "worst_case": 0.85,
}

# Minimum acceptable funnel stage rates
MIN_STAGE_RATES = {
    "impression_to_click": 0.005,
    "click_to_visit": 0.50,
    "visit_to_cart": 0.02,
    "cart_to_checkout": 0.15,
    "checkout_to_purchase": 0.30,
}


RULES = [
    {
        "id": "conversion_rate_realistic",
        "name": "Conversion rate within realistic bounds",
        "description": "Overall conversion rate must be between 0.5% and 25%",
        "check": lambda data: 0.005 <= data.get("conversion_rate", 0) / 100.0 <= 0.25,
        "severity": "blocker",
        "action": "Conversion rate outside realistic bounds — recheck inputs",
    },
    {
        "id": "cold_traffic_cap",
        "name": "Cold traffic conversion cap",
        "description": "Cold traffic (paid ads) should not exceed 5% conversion",
        "check": lambda data: (
            data.get("traffic_source", "") not in ("paid_social", "paid_search")
            or data.get("conversion_rate", 0) <= 5.0
        ),
        "severity": "warning",
        "action": "Cold traffic converting above 5% is unusual — validate data",
    },
    {
        "id": "cart_abandonment_sanity",
        "name": "Cart abandonment rate sanity",
        "description": "Cart-to-checkout rate below 15% indicates severe UX issues",
        "check": lambda data: data.get("funnel", {}).get("cart_to_checkout", 100) >= 15.0,
        "severity": "warning",
        "action": "Cart abandonment is extreme — check checkout UX, shipping costs, trust signals",
    },
    {
        "id": "zero_reviews_penalty",
        "name": "Zero reviews warning",
        "description": "Products with 0 reviews have 50% lower conversion than benchmarks",
        "check": lambda data: data.get("review_count", 0) > 0,
        "severity": "info",
        "action": "No reviews detected — expect 40-60% lower conversion. Prioritize getting first 10 reviews",
    },
    {
        "id": "high_price_low_conversion",
        "name": "High price conversion check",
        "description": "Products over $100 with >5% conversion may have data issues",
        "check": lambda data: (
            data.get("price", 0) <= 100
            or data.get("conversion_rate", 0) <= 5.0
        ),
        "severity": "warning",
        "action": "High-price product with high conversion — verify this is not a data error",
    },
    {
        "id": "minimum_visitors_for_significance",
        "name": "Minimum traffic for statistical significance",
        "description": "Need at least 100 daily visitors for meaningful conversion data",
        "check": lambda data: data.get("daily_visitors", 0) >= 100,
        "severity": "info",
        "action": "Low traffic volume — conversion estimates have wide confidence intervals",
    },
]


def evaluate_rules(conversion_data: dict[str, Any]) -> dict[str, Any]:
    """Run all conversion rules against the estimation data.

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
            passed = rule["check"](conversion_data)
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
