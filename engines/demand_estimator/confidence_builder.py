"""Demand Estimator Engine — confidence builder.

Build confidence intervals around the demand estimate.
"""
from __future__ import annotations

import copy
from typing import Any


def build_confidence(
    **kwargs: Any,
) -> dict[str, Any]:
    """Build confidence intervals.

    Args:
        **kwargs: Must include adjustment data.

    Returns:
        Structured dict with confidence intervals.
    """
    try:
        adj_data = kwargs.get("adjustment_calculator_data", {})
        adjusted = float(adj_data.get("adjusted_demand", 0))
        base = float(adj_data.get("base_demand", 0))
        product = kwargs.get("product", {})
        market_size = float(kwargs.get("market_size", 0))

        # Confidence based on data quality signals
        has_historical = bool(product.get("historical_sales"))
        has_competition = adj_data.get("num_competitors", 0) > 0
        data_signals = sum([has_historical, has_competition, market_size > 0])
        confidence = round(min(0.5 + data_signals * 0.15, 0.95), 2)

        # Build intervals
        margin = (1 - confidence) * adjusted if adjusted > 0 else 0
        low = round(max(0, adjusted - margin))
        high = round(adjusted + margin)

        return {
            "status": "success",
            "result": {
                "adjusted_demand": adjusted,
                "confidence": confidence,
                "low": low,
                "high": high,
                "margin": round(margin),
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Confidence building failed: {exc}"}
