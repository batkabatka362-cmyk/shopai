"""Volume projection rules — hard constraints and guardrails.

Rules that MUST be checked before committing to inventory or product launch.
Violations = automatic rejection or mandatory warning.

Core principles:
  - Min 30 units/month for a viable product (below this, margins won't work)
  - Inventory must cover 2 months of projected demand
  - Reorder at 60% depletion (don't wait until stockout)
"""
from __future__ import annotations

from typing import Any


RULES = [
    {
        "id": "min_viable_volume",
        "name": "Minimum viable monthly volume",
        "description": "Projected monthly volume must be at least 30 units. "
                       "Below this threshold, per-unit costs are too high and "
                       "margins won't cover fixed operating expenses.",
        "check": lambda data: (
            data.get("expected_monthly_volume", 0) >= 30
        ),
        "severity": "blocker",
        "action": "Do not proceed — volume too low for profitable operations",
    },
    {
        "id": "pessimistic_floor",
        "name": "Pessimistic scenario floor",
        "description": "Even the pessimistic scenario (60% of expected) should yield "
                       "at least 15 units/month. If worst case is under 15, risk is too high.",
        "check": lambda data: (
            data.get("expected_monthly_volume", 0) * 0.60 >= 15
        ),
        "severity": "warning",
        "action": "High risk — worst-case volume is dangerously low",
    },
    {
        "id": "inventory_two_month_coverage",
        "name": "Inventory covers 2 months of demand",
        "description": "Initial inventory order must cover at least 2 months of projected "
                       "demand to avoid stockouts during supplier lead times.",
        "check": lambda data: (
            data.get("order_quantity", 0) >=
            data.get("expected_monthly_volume", 0) * 2
        ),
        "severity": "blocker",
        "action": "Increase order quantity to cover 2 months of projected demand",
    },
    {
        "id": "reorder_at_60pct",
        "name": "Reorder trigger at 60% depletion",
        "description": "Reorder point must be set at 40% remaining stock (60% depleted). "
                       "Waiting longer risks stockouts given typical 2-4 week lead times.",
        "check": lambda data: (
            data.get("reorder_threshold_pct", 0) >= 0.55
        ),
        "severity": "warning",
        "action": "Set reorder trigger to 60% depletion (40% remaining)",
    },
    {
        "id": "new_product_ramp_awareness",
        "name": "New product ramp expectation",
        "description": "Products under 3 months old should expect only 40-70% of "
                       "steady-state volume. Projections must apply growth ramp.",
        "check": lambda data: (
            data.get("product_age_months", 12) >= 3 or
            data.get("ramp_applied", False)
        ),
        "severity": "info",
        "action": "Month 1 sales = 40% of expected. Don't panic — ramp is normal.",
    },
    {
        "id": "seasonal_adjustment_applied",
        "name": "Seasonal adjustment required",
        "description": "Volume projections must account for seasonal variation. "
                       "Q4 can be 150-200% of average; Q1 can be 60-80%.",
        "check": lambda data: (
            data.get("seasonal_factor_applied", False) or
            data.get("target_month") is None
        ),
        "severity": "warning",
        "action": "Apply seasonal adjustments — raw projections can be misleading",
    },
    {
        "id": "max_initial_investment",
        "name": "First order investment cap",
        "description": "First inventory order should not exceed $5,000 for unvalidated "
                       "products. Validate with a small batch first.",
        "check": lambda data: (
            data.get("inventory_investment", 0) <= 5000 or
            data.get("product_validated", False)
        ),
        "severity": "warning",
        "action": "Consider a smaller test batch before committing full inventory budget",
    },
]


def evaluate_rules(projection_data: dict[str, Any]) -> dict[str, Any]:
    """Run all volume projection rules against the data.

    Args:
        projection_data: Combined projection and inventory data.

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
            passed = rule["check"](projection_data)
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
