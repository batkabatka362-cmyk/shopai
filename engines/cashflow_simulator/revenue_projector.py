"""Cashflow Simulator Engine — revenue projector.

Projects revenue with growth rate and seasonality factors.
"""
from __future__ import annotations

import copy
from typing import Any

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def project_revenue(
    monthly_revenue: float,
    growth_rate: float,
    seasonality: dict[str, float],
    months: int = 12,
    start_month: int = 1,
) -> dict[str, Any]:
    """Project monthly revenue with growth and seasonality."""
    try:
        projections: list[dict[str, Any]] = []
        for i in range(months):
            month_idx = (start_month - 1 + i) % 12
            month_label = _MONTH_NAMES[month_idx]

            # Compound growth
            growth_factor = (1 + growth_rate / 100.0) ** i
            # Seasonality multiplier
            season_factor = float(seasonality.get(month_label, seasonality.get(str(month_idx + 1), 1.0)))

            revenue = round(monthly_revenue * growth_factor * season_factor, 2)
            projections.append({
                "month": i + 1,
                "month_label": month_label,
                "revenue": revenue,
                "growth_factor": round(growth_factor, 4),
                "season_factor": round(season_factor, 2),
            })

        return {"status": "success", "projections": projections}
    except Exception as exc:
        return {"status": "error", "projections": [], "error": f"Revenue projection failed: {exc}"}
