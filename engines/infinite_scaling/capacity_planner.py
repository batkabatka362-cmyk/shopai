"""Infinite Scaling Engine — capacity planner.

Plan capacity for projected growth.
"""
from __future__ import annotations

import copy
from typing import Any


def plan_capacity(
    **kwargs: Any,
) -> dict[str, Any]:
    """Plan capacity for growth.

    Args:
        **kwargs: Must include resources, growth data, bottleneck data.

    Returns:
        Structured dict with capacity plan.
    """
    try:
        resources = copy.deepcopy(kwargs.get("resources", {}))
        growth_data = kwargs.get("growth_analyzer_data", {})
        bottleneck_data = kwargs.get("bottleneck_finder_data", {})
        growth_targets = kwargs.get("growth_targets", {})

        trajectory = growth_data.get("growth_trajectory", {})
        target_growth = float(growth_targets.get("target_growth_pct", 20))
        months_horizon = int(growth_targets.get("months_horizon", 12))

        current_revenue = float(trajectory.get("monthly_revenue", 0))
        current_orders = int(trajectory.get("monthly_orders", 0))
        current_customers = int(trajectory.get("active_customers", 0))

        # Project capacity needs
        growth_multiplier = (1 + target_growth / 100) ** (months_horizon / 12)
        projected_revenue = round(current_revenue * growth_multiplier, 2)
        projected_orders = round(current_orders * growth_multiplier)
        projected_customers = round(current_customers * growth_multiplier)

        # Team needs
        current_team = int(resources.get("team_size", 1))
        needed_team = max(current_team, round(projected_orders / 400))  # 400 orders/person target

        capacity_plan = {
            "horizon_months": months_horizon,
            "projected_revenue": projected_revenue,
            "projected_orders": projected_orders,
            "projected_customers": projected_customers,
            "current_team": current_team,
            "needed_team": needed_team,
            "team_gap": max(0, needed_team - current_team),
            "growth_multiplier": round(growth_multiplier, 2),
        }

        return {
            "status": "success",
            "result": {"capacity_plan": capacity_plan},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Capacity planning failed: {exc}"}
