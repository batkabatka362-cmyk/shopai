"""Demand Estimator Engine — scenario modeler.

Model best/worst/expected scenarios for demand.
"""
from __future__ import annotations

import copy
from typing import Any


def model_scenarios(
    **kwargs: Any,
) -> dict[str, Any]:
    """Model demand scenarios.

    Args:
        **kwargs: Must include all prior stage data.

    Returns:
        Structured dict with scenario models.
    """
    try:
        adj_data = kwargs.get("adjustment_calculator_data", {})
        conf_data = kwargs.get("confidence_builder_data", {})

        base = float(adj_data.get("base_demand", 0))
        adjusted = float(adj_data.get("adjusted_demand", 0))
        low = float(conf_data.get("low", 0))
        high = float(conf_data.get("high", 0))
        confidence = float(conf_data.get("confidence", 0.5))

        scenarios = {
            "best_case": {
                "demand": high,
                "probability": round(0.15, 2),
                "description": "Favorable market conditions, weak competition",
            },
            "expected": {
                "demand": adjusted,
                "probability": round(0.60, 2),
                "description": "Normal market conditions",
            },
            "worst_case": {
                "demand": low,
                "probability": round(0.25, 2),
                "description": "Increased competition, market slowdown",
            },
        }

        estimate = {
            "base": base,
            "adjusted": adjusted,
            "low": low,
            "high": high,
            "expected": adjusted,
        }

        return {
            "status": "success",
            "result": {
                "estimate": estimate,
                "confidence": confidence,
                "scenarios": scenarios,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Scenario modeling failed: {exc}"}
