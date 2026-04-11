"""Demand Analysis Engine — velocity calculator.

Calculate demand velocity (rate of change in demand over time).
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_velocity(
    **kwargs: Any,
) -> dict[str, Any]:
    """Calculate demand velocity.

    Args:
        **kwargs: Must include market_data and volume_estimator_data.

    Returns:
        Structured dict with velocity metrics.
    """
    try:
        market_data = copy.deepcopy(kwargs.get("market_data", {}))
        vol_data = kwargs.get("volume_estimator_data", {})
        growth_rate = float(vol_data.get("growth_rate", 0))

        # Velocity = rate of change in growth
        prev_growth = float(market_data.get("prev_growth_rate", 0))
        acceleration = round(growth_rate - prev_growth, 2)

        if acceleration > 5:
            velocity_label = "accelerating"
        elif acceleration > 0:
            velocity_label = "steady_growth"
        elif acceleration > -5:
            velocity_label = "decelerating"
        else:
            velocity_label = "declining"

        return {
            "status": "success",
            "result": {
                "velocity": growth_rate,
                "acceleration": acceleration,
                "velocity_label": velocity_label,
                "prev_growth_rate": prev_growth,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Velocity calculation failed: {exc}"}
