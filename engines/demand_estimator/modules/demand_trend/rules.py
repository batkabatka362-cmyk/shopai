"""Demand trend rules — hard constraints and guardrails.

Rules that MUST be checked before making market entry or inventory decisions
based on demand trend analysis.

Core principles:
  - Don't enter declining markets (>10% YoY drop)
  - Require 2+ months of trend data before making decisions
  - Seasonal adjustments are required (raw data is misleading)
"""
from __future__ import annotations

from typing import Any


RULES = [
    {
        "id": "no_declining_markets",
        "name": "Do not enter declining markets",
        "description": "Markets with >10% year-over-year decline are losing demand. "
                       "Winning in a declining market means stealing share from "
                       "established players — much harder than riding a growing wave.",
        "check": lambda data: (
            data.get("yoy_change_pct") is None or
            data.get("yoy_change_pct", 0) >= -10
        ),
        "severity": "blocker",
        "action": "Do not enter this market — demand is declining >10% YoY",
    },
    {
        "id": "min_trend_data",
        "name": "Minimum trend data required",
        "description": "At least 2 months of trend data are required before making "
                       "any inventory or market entry decisions. A single month of "
                       "data could be an anomaly.",
        "check": lambda data: (
            data.get("data_points", 0) >= 2
        ),
        "severity": "blocker",
        "action": "Collect more data — at least 2 months needed for trend analysis",
    },
    {
        "id": "seasonal_adjustment_required",
        "name": "Seasonal adjustments must be applied",
        "description": "Raw demand data without seasonal adjustment can be misleading. "
                       "Q4 data inflates demand estimates; Q1 data deflates them. "
                       "Always normalize for seasonality before deciding.",
        "check": lambda data: (
            data.get("seasonal_adjusted", False) or
            data.get("direction") != "seasonal"
        ),
        "severity": "warning",
        "action": "Apply seasonal adjustments before making decisions on this data",
    },
    {
        "id": "fad_detection",
        "name": "Fad detection warning",
        "description": "If demand spiked >100% in the last 3 months with no prior "
                       "history, this could be a fad. Fads crash as fast as they rise.",
        "check": lambda data: (
            data.get("recent_pct_change", 0) <= 100 or
            data.get("trend_age_months", 12) >= 6
        ),
        "severity": "warning",
        "action": "Possible fad — start with small inventory and validate demand persistence",
    },
    {
        "id": "steep_decline_abort",
        "name": "Steep decline emergency signal",
        "description": "If demand has dropped >25% in the last 3 months, something "
                       "fundamental has changed. Do not commit new inventory.",
        "check": lambda data: (
            data.get("recent_pct_change", 0) >= -25
        ),
        "severity": "blocker",
        "action": "Abort — demand has dropped >25% recently. Investigate cause before proceeding.",
    },
    {
        "id": "conflicting_signals",
        "name": "Conflicting signal warning",
        "description": "If search volume trend and sales trend diverge (one growing, "
                       "one declining), the data is unreliable. Investigate before acting.",
        "check": lambda data: not (
            data.get("search_trend") == "growing" and
            data.get("sales_trend") == "declining"
        ),
        "severity": "warning",
        "action": "Conflicting demand signals — search up but sales down. Investigate conversion issues.",
    },
    {
        "id": "ceiling_proximity",
        "name": "Demand ceiling proximity",
        "description": "If demand appears to be hitting a ceiling (growth decelerating "
                       "toward zero), volume projections should use ceiling value, not "
                       "extrapolated growth.",
        "check": lambda data: not data.get("ceiling_detected", False),
        "severity": "info",
        "action": "Demand ceiling detected — use plateau value for projections, not growth extrapolation",
    },
]


def evaluate_rules(trend_data: dict[str, Any]) -> dict[str, Any]:
    """Run all demand trend rules against the data.

    Args:
        trend_data: Combined trend analysis data including direction,
                    velocity, YoY changes, and metadata.

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
            passed = rule["check"](trend_data)
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
