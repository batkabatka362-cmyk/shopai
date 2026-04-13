"""Infinite Scaling Engine — scaling advisor.

Advise on scaling strategy based on growth, bottlenecks, and capacity.
"""
from __future__ import annotations

import copy
from typing import Any


def advise_scaling(
    **kwargs: Any,
) -> dict[str, Any]:
    """Advise on scaling strategy.

    Args:
        **kwargs: Must include all prior stage data.

    Returns:
        Structured dict with scaling recommendations.
    """
    try:
        growth_data = kwargs.get("growth_analyzer_data", {})
        bottleneck_data = kwargs.get("bottleneck_finder_data", {})
        capacity_data = kwargs.get("capacity_planner_data", {})

        trajectory = growth_data.get("growth_trajectory", {})
        bottlenecks = bottleneck_data.get("bottlenecks", [])
        capacity_plan = capacity_data.get("capacity_plan", {})

        phase = trajectory.get("phase", "stable")
        recommendations: list[dict[str, Any]] = []

        # Phase-specific recommendations
        if phase == "hypergrowth":
            recommendations.append({
                "priority": "critical",
                "area": "infrastructure",
                "recommendation": "Scale infrastructure proactively — demand may outpace capacity",
            })
        elif phase == "declining":
            recommendations.append({
                "priority": "high",
                "area": "strategy",
                "recommendation": "Pivot strategy — focus on retention and new market opportunities",
            })

        # Bottleneck-specific recommendations
        for bn in bottlenecks:
            recommendations.append({
                "priority": bn.get("severity", "medium"),
                "area": bn.get("area", "general"),
                "recommendation": bn.get("recommendation", ""),
            })

        # Capacity gap recommendations
        team_gap = capacity_plan.get("team_gap", 0)
        if team_gap > 0:
            recommendations.append({
                "priority": "high",
                "area": "hiring",
                "recommendation": f"Hire {team_gap} additional team members within planning horizon",
            })

        # Sort by priority
        pri_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recommendations.sort(key=lambda r: pri_order.get(r.get("priority", "low"), 4))

        return {
            "status": "success",
            "result": {
                "growth_trajectory": trajectory,
                "bottlenecks": bottlenecks,
                "capacity_plan": capacity_plan,
                "scaling_recommendations": recommendations,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Scaling advice failed: {exc}"}
