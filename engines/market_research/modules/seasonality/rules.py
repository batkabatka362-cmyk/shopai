"""Seasonality rules — timing constraints and guardrails.

Hard rules that prevent bad seasonal decisions:
  - Don't launch during trough
  - Don't run out of stock before peak
  - Don't spend heavily during low season
"""
from __future__ import annotations

import time
from typing import Any


RULES = [
    {
        "id": "no_launch_in_trough",
        "name": "No product launch during seasonal trough",
        "description": "Don't launch new products when demand is at yearly low",
        "check": lambda data: data.get("current_index", 100) >= 75,
        "severity": "warning",
        "action": "Delay launch to next rising period",
    },
    {
        "id": "prep_before_peak",
        "name": "Prepare inventory before peak",
        "description": "Must order extra inventory at least 6 weeks before seasonal peak",
        "check": lambda data: _check_peak_prep(data),
        "severity": "blocker",
        "action": "Order additional inventory NOW for upcoming peak",
    },
    {
        "id": "no_clearance_before_peak",
        "name": "No deep discounts before peak",
        "description": "Don't run clearance sales within 8 weeks of seasonal peak",
        "check": lambda data: _check_no_clearance_before_peak(data),
        "severity": "warning",
        "action": "Hold inventory for peak — clearance will cannibalize full-price sales",
    },
    {
        "id": "reduce_spend_in_trough",
        "name": "Reduce ad spend in low season",
        "description": "Ad spend ROI drops significantly during seasonal lows",
        "check": lambda data: not (data.get("current_index", 100) < 75 and data.get("ad_spend_high", False)),
        "severity": "warning",
        "action": "Reduce ad budget and focus on content/SEO during low season",
    },
    {
        "id": "highly_seasonal_awareness",
        "name": "Highly seasonal category warning",
        "description": "Products with variability > 40% have extreme revenue swings",
        "check": lambda data: data.get("variability_index", 0) <= 40,
        "severity": "info",
        "action": "Plan cash reserves for trough months. Revenue will drop 50%+ in low season.",
    },
]


def evaluate_rules(seasonality_data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all seasonality rules."""
    blockers = []
    warnings = []
    info = []

    for rule in RULES:
        try:
            passed = rule["check"](seasonality_data)
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


def _check_peak_prep(data: dict[str, Any]) -> bool:
    """Check if we're prepared for upcoming peak."""
    months_to_peak = data.get("months_to_peak")
    if months_to_peak is None:
        return True
    # If peak is within 6 weeks (1.5 months) and we haven't prepped
    return not (months_to_peak <= 2 and not data.get("peak_inventory_ordered", False))


def _check_no_clearance_before_peak(data: dict[str, Any]) -> bool:
    """Check that we're not running clearance right before a peak."""
    months_to_peak = data.get("months_to_peak")
    if months_to_peak is None:
        return True
    return not (months_to_peak <= 2 and data.get("running_clearance", False))
