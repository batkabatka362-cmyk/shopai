"""LTV:CAC Dashboard Engine — ratio tracker.

Tracks LTV:CAC ratio over time and determines trend.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def track_ratio(
    ltv: dict[str, Any],
    cac: dict[str, Any],
) -> dict[str, Any]:
    """Calculate and track LTV:CAC ratio.

    Args:
        ltv: LTV result from ltv_calculator.
        cac: CAC result from cac_calculator.

    Returns:
        Structured dict with ratio, trend, and payback months.
    """
    try:
        avg_ltv = float(ltv.get("average", 0.0))
        avg_cac = float(cac.get("average", 0.0))

        ratio = round(avg_ltv / avg_cac, 2) if avg_cac > 0 else 0.0

        # Payback period estimate (months)
        # Assume average customer lifespan of 24 months
        monthly_rev = avg_ltv / 24.0 if avg_ltv > 0 else 0.0
        payback_months = round(avg_cac / monthly_rev, 1) if monthly_rev > 0 else 0.0

        # Trend assessment
        if ratio >= 5.0:
            trend = "excellent"
        elif ratio >= 3.0:
            trend = "healthy"
        elif ratio >= 1.5:
            trend = "acceptable"
        elif ratio >= 1.0:
            trend = "concerning"
        else:
            trend = "critical"

        return {
            "status": "success",
            "ratio": ratio,
            "trend": trend,
            "payback_months": payback_months,
        }
    except Exception as exc:
        return {"status": "error", "ratio": 0.0, "trend": "unknown", "payback_months": 0.0, "error": f"Ratio tracking failed: {exc}"}
