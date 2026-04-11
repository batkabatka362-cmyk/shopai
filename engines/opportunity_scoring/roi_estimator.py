"""Opportunity Scoring Engine — ROI estimator.

Estimates return on investment for each opportunity based on
potential revenue, costs, and timeline.
"""
from __future__ import annotations

import copy
from typing import Any


def estimate_roi(
    assessed: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate ROI for each assessed opportunity.

    Args:
        assessed: Risk-assessed opportunities.

    Returns:
        Structured dict with ROI estimates.
    """
    try:
        opps = copy.deepcopy(assessed)
        estimated: list[dict[str, Any]] = []

        for opp in opps:
            potential = float(opp.get("potential_revenue", opp.get("market_size", 0)))
            effort = str(opp.get("effort", "medium"))
            feasibility = float(opp.get("feasibility", 0.5))

            # Estimate cost based on effort
            effort_costs = {"low": 5000, "medium": 25000, "high": 100000}
            estimated_cost = effort_costs.get(effort, 25000)

            # Adjusted potential based on feasibility
            adjusted_potential = potential * feasibility

            # ROI = (gain - cost) / cost * 100
            if estimated_cost > 0:
                roi = round((adjusted_potential - estimated_cost) / estimated_cost * 100, 1)
            else:
                roi = 0.0

            # Payback period in months
            monthly_revenue = adjusted_potential / 12 if adjusted_potential > 0 else 0
            payback_months = (
                round(estimated_cost / monthly_revenue, 1)
                if monthly_revenue > 0 else float("inf")
            )

            opp["roi"] = roi
            opp["estimated_cost"] = estimated_cost
            opp["adjusted_potential"] = round(adjusted_potential, 2)
            opp["payback_months"] = payback_months if payback_months != float("inf") else -1
            estimated.append(opp)

        return {
            "status": "success",
            "estimated": estimated,
            "total_estimated": len(estimated),
        }
    except Exception as exc:
        return {
            "status": "error",
            "estimated": [],
            "error": f"ROI estimation failed: {exc}",
        }
