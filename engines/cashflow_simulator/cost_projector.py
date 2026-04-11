"""Cashflow Simulator Engine — cost projector.

Projects costs including variable and fixed components.
"""
from __future__ import annotations

import copy
from typing import Any


def project_costs(
    monthly_costs: float,
    revenue_projections: list[dict[str, Any]],
    monthly_revenue: float,
    months: int = 12,
) -> dict[str, Any]:
    """Project monthly costs with fixed/variable split."""
    try:
        # Assume 60% fixed, 40% variable (scales with revenue)
        fixed_pct = 0.6
        variable_pct = 0.4

        fixed_cost = monthly_costs * fixed_pct
        variable_base = monthly_costs * variable_pct

        projections: list[dict[str, Any]] = []
        for i, rev_proj in enumerate(revenue_projections[:months]):
            revenue = float(rev_proj.get("revenue", monthly_revenue))
            revenue_ratio = revenue / max(monthly_revenue, 1)

            variable_cost = round(variable_base * revenue_ratio, 2)
            total_cost = round(fixed_cost + variable_cost, 2)

            # Annual cost increases (2% per year)
            annual_inflation = (1 + 0.02 / 12) ** i
            total_cost = round(total_cost * annual_inflation, 2)

            projections.append({
                "month": i + 1,
                "month_label": rev_proj.get("month_label", ""),
                "fixed_cost": round(fixed_cost * annual_inflation, 2),
                "variable_cost": round(variable_cost * annual_inflation, 2),
                "total_cost": total_cost,
            })

        return {"status": "success", "projections": projections}
    except Exception as exc:
        return {"status": "error", "projections": [], "error": f"Cost projection failed: {exc}"}
