"""Infinite Scaling Engine — bottleneck finder.

Find scaling bottlenecks in resources, processes, and systems.
"""
from __future__ import annotations

import copy
from typing import Any


def find_bottlenecks(
    **kwargs: Any,
) -> dict[str, Any]:
    """Find scaling bottlenecks.

    Args:
        **kwargs: Must include 'resources' dict and growth data.

    Returns:
        Structured dict with identified bottlenecks.
    """
    try:
        resources = copy.deepcopy(kwargs.get("resources", {}))
        growth_data = kwargs.get("growth_analyzer_data", {})
        trajectory = growth_data.get("growth_trajectory", {})
        growth_targets = kwargs.get("growth_targets", {})

        bottlenecks: list[dict[str, Any]] = []

        # Check team capacity
        team_size = int(resources.get("team_size", 0))
        orders = int(trajectory.get("monthly_orders", 0))
        orders_per_person = orders / max(team_size, 1)
        if orders_per_person > 500:
            bottlenecks.append({
                "area": "team_capacity",
                "severity": "high",
                "detail": f"{orders_per_person:.0f} orders/person — team overwhelmed",
                "recommendation": "Hire additional team members or automate order processing",
            })

        # Check inventory/fulfillment
        fulfillment_rate = float(resources.get("fulfillment_rate", 1.0))
        if fulfillment_rate < 0.95:
            bottlenecks.append({
                "area": "fulfillment",
                "severity": "high" if fulfillment_rate < 0.85 else "medium",
                "detail": f"Fulfillment rate at {fulfillment_rate*100:.1f}%",
                "recommendation": "Expand warehouse capacity or add fulfillment partners",
            })

        # Check technology
        uptime = float(resources.get("system_uptime", 0.999))
        if uptime < 0.99:
            bottlenecks.append({
                "area": "technology",
                "severity": "high",
                "detail": f"System uptime at {uptime*100:.2f}%",
                "recommendation": "Invest in infrastructure reliability",
            })

        # Check budget vs growth target
        target_growth = float(growth_targets.get("target_growth_pct", 0))
        current_growth = float(trajectory.get("revenue_growth_pct", 0))
        if target_growth > 0 and current_growth < target_growth * 0.5:
            bottlenecks.append({
                "area": "growth_gap",
                "severity": "medium",
                "detail": f"Growing at {current_growth}% vs {target_growth}% target",
                "recommendation": "Review marketing spend and conversion optimization",
            })

        bottlenecks.sort(key=lambda b: {"high": 0, "medium": 1, "low": 2}.get(b["severity"], 3))

        return {
            "status": "success",
            "result": {"bottlenecks": bottlenecks},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Bottleneck finding failed: {exc}"}
