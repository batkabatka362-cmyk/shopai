"""Demand Analysis Engine — saturation checker.

Check market saturation level to determine remaining opportunity.
"""
from __future__ import annotations

import copy
from typing import Any


def check_saturation(
    **kwargs: Any,
) -> dict[str, Any]:
    """Check market saturation.

    Args:
        **kwargs: Must include all prior stage data.

    Returns:
        Structured dict with saturation assessment.
    """
    try:
        vol_data = kwargs.get("volume_estimator_data", {})
        vel_data = kwargs.get("velocity_calculator_data", {})
        seg_data = kwargs.get("segment_decomposer_data", {})
        products = kwargs.get("products", [])
        market_data = kwargs.get("market_data", {})

        growth_rate = float(vol_data.get("growth_rate", 0))
        velocity_label = vel_data.get("velocity_label", "steady_growth")
        segments = seg_data.get("segments", [])
        num_competitors = int(market_data.get("num_competitors", 1))

        # Saturation heuristic: low growth + many competitors = saturated
        saturation_score = 0.0
        if growth_rate < 2:
            saturation_score += 0.3
        if velocity_label in ("decelerating", "declining"):
            saturation_score += 0.3
        if num_competitors > 20:
            saturation_score += 0.2
        elif num_competitors > 10:
            saturation_score += 0.1
        # Check if any segment still growing fast
        fast_growing = [s for s in segments if s.get("growth_rate", 0) > 10]
        if not fast_growing:
            saturation_score += 0.2

        saturation_level = round(min(saturation_score, 1.0), 2)
        label = "low" if saturation_level < 0.3 else "medium" if saturation_level < 0.6 else "high"

        demand = {
            "total_volume": vol_data.get("total_market_volume", 0),
            "velocity": vel_data.get("velocity", 0),
            "growth_rate": growth_rate,
        }

        return {
            "status": "success",
            "result": {
                "demand": demand,
                "segments": segments,
                "saturation_level": saturation_level,
                "saturation_label": label,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Saturation check failed: {exc}"}
