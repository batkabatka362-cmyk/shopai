"""Financial Engine — health grader.

Grades overall financial health A through F based on
margins, revenue growth, cost efficiency, and cash position.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Grade thresholds
# ---------------------------------------------------------------------------

_GRADE_THRESHOLDS = [
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
    (0, "F"),
]


def grade_health(
    revenue: dict[str, Any],
    costs: dict[str, Any],
    margins: dict[str, Any],
) -> dict[str, Any]:
    """Grade overall financial health.

    Args:
        revenue: Revenue breakdown.
        costs: Cost breakdown.
        margins: Margin analysis.

    Returns:
        Structured dict with health grade and factors.
    """
    try:
        total_revenue = float(revenue.get("total_revenue", 0))
        gross_margin_pct = float(margins.get("gross_margin_pct", 0))
        net_margin_pct = float(margins.get("net_margin_pct", 0))
        cost_per_order = float(costs.get("cost_per_order", 0))
        avg_order_value = float(revenue.get("avg_order_value", 0))

        # Factor scores (0 to 100)
        margin_score = min(100, max(0, gross_margin_pct * 2))
        profitability_score = min(100, max(0, (net_margin_pct + 20) * 2.5))

        efficiency = (
            round((1 - cost_per_order / avg_order_value) * 100, 1)
            if avg_order_value > 0 else 0.0
        )
        efficiency_score = min(100, max(0, efficiency))

        revenue_score = min(100, max(0, 50 + (total_revenue / 1000)))

        factors = {
            "margin": round(margin_score, 1),
            "profitability": round(profitability_score, 1),
            "efficiency": round(efficiency_score, 1),
            "revenue": round(revenue_score, 1),
        }

        overall_score = round(
            margin_score * 0.3 +
            profitability_score * 0.3 +
            efficiency_score * 0.2 +
            revenue_score * 0.2,
            1,
        )

        grade = "F"
        for threshold, g in _GRADE_THRESHOLDS:
            if overall_score >= threshold:
                grade = g
                break

        recommendations: list[str] = []
        if gross_margin_pct < 30:
            recommendations.append("Improve gross margins — review pricing or negotiate supplier costs")
        if net_margin_pct < 5:
            recommendations.append("Net margins are thin — reduce operating expenses")
        if efficiency_score < 50:
            recommendations.append("Cost per order is high — optimize fulfillment and operations")
        if not recommendations:
            recommendations.append("Financial health is strong — maintain current trajectory")

        return {
            "status": "success",
            "health": {
                "grade": grade,
                "score": overall_score,
                "factors": factors,
                "recommendations": recommendations,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "health": {},
            "error": f"Health grading failed: {exc}",
        }
