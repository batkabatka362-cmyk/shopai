"""Demand Estimator Engine — adjustment calculator.

Adjust base demand for competition, seasonality, and market conditions.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_adjustments(
    **kwargs: Any,
) -> dict[str, Any]:
    """Calculate demand adjustments.

    Args:
        **kwargs: Must include base estimate, competition, seasonality.

    Returns:
        Structured dict with adjusted demand.
    """
    try:
        base_data = kwargs.get("base_estimator_data", {})
        base_demand = float(base_data.get("base_demand", 0))
        competition = kwargs.get("competition", {})
        seasonality = kwargs.get("seasonality", {})

        # Competition adjustment
        num_competitors = int(competition.get("num_competitors", 1))
        competition_intensity = float(competition.get("intensity", 0.5))
        comp_factor = max(0.3, 1.0 - competition_intensity * 0.5)

        # Seasonality adjustment
        season_factor = float(seasonality.get("current_factor", 1.0))
        peak_months = seasonality.get("peak_months", [])

        adjusted = round(base_demand * comp_factor * season_factor)

        return {
            "status": "success",
            "result": {
                "base_demand": base_demand,
                "adjusted_demand": adjusted,
                "competition_factor": round(comp_factor, 3),
                "seasonality_factor": season_factor,
                "num_competitors": num_competitors,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Adjustment calculation failed: {exc}"}
