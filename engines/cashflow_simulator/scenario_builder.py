"""Cashflow Simulator Engine — scenario builder.

Builds best/worst/expected cash flow scenarios.
"""
from __future__ import annotations

import copy
from typing import Any


def build_scenarios(
    revenue_projections: list[dict[str, Any]],
    cost_projections: list[dict[str, Any]],
    current_balance: float,
) -> dict[str, Any]:
    """Build best, worst, and expected scenarios."""
    try:
        scenarios: dict[str, dict[str, Any]] = {}

        multipliers = {
            "best": {"revenue": 1.2, "cost": 0.9},
            "expected": {"revenue": 1.0, "cost": 1.0},
            "worst": {"revenue": 0.7, "cost": 1.15},
        }

        for scenario_name, mults in multipliers.items():
            balance = current_balance
            monthly: list[dict[str, Any]] = []
            total_revenue = 0.0
            total_costs = 0.0

            for i in range(len(revenue_projections)):
                rev = round(float(revenue_projections[i].get("revenue", 0)) * mults["revenue"], 2)
                cost = round(float(cost_projections[i].get("total_cost", 0)) * mults["cost"], 2)
                net = round(rev - cost, 2)
                balance = round(balance + net, 2)
                total_revenue += rev
                total_costs += cost

                monthly.append({
                    "month": i + 1,
                    "month_label": revenue_projections[i].get("month_label", ""),
                    "revenue": rev,
                    "costs": cost,
                    "net": net,
                    "balance": balance,
                })

            scenarios[scenario_name] = {
                "name": scenario_name,
                "projections": monthly,
                "final_balance": balance,
                "total_revenue": round(total_revenue, 2),
                "total_costs": round(total_costs, 2),
            }

        return {"status": "success", "scenarios": scenarios}
    except Exception as exc:
        return {"status": "error", "scenarios": {}, "error": f"Scenario building failed: {exc}"}
