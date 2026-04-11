"""Supplier Discovery Engine — recommendation builder.

Build supplier recommendations combining qualifications, costs, and fit.
"""
from __future__ import annotations

import copy
from typing import Any


def build_recommendations(
    **kwargs: Any,
) -> dict[str, Any]:
    """Build supplier recommendations.

    Args:
        **kwargs: Must include qualification and cost data.

    Returns:
        Structured dict with ranked supplier recommendations.
    """
    try:
        qual_data = kwargs.get("qualification_checker_data", {})
        cost_data = kwargs.get("cost_comparator_data", {})
        qualified = copy.deepcopy(qual_data.get("qualified", []))
        comparisons = cost_data.get("comparison", [])
        cost_map = {c["supplier"]: c for c in comparisons}

        recommendations: list[dict[str, Any]] = []

        for sup in qualified:
            name = sup.get("name", "unknown")
            qual_score = float(sup.get("qualification_score", 0))
            cost_info = cost_map.get(name, {})
            within_budget = cost_info.get("within_budget", True)

            # Composite score
            cost_score = 1.0 if within_budget else 0.5
            overall = round(qual_score * 0.6 + cost_score * 0.4, 2)

            recommendations.append({
                "name": name,
                "region": sup.get("region", ""),
                "moq": sup.get("moq", 0),
                "lead_time": sup.get("lead_time_days", 0),
                "cost": cost_info.get("unit_cost", 0),
                "qualification_score": qual_score,
                "overall_score": overall,
            })

        recommendations.sort(key=lambda r: r["overall_score"], reverse=True)
        recommended = recommendations[:3] if recommendations else []

        return {
            "status": "success",
            "result": {
                "suppliers": recommendations,
                "recommended": recommended,
                "comparison": cost_data.get("comparison", []),
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Recommendation building failed: {exc}"}
