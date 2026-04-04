"""Customer Behavior Simulator Engine — retention predictor.

Predicts retention impact of simulated actions on each segment.
"""
from __future__ import annotations

import copy
from typing import Any


def predict_retention(
    simulations: list[dict[str, Any]],
    behavior_patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    """Predict retention changes per segment."""
    try:
        pattern_map = {p.get("segment", ""): p for p in behavior_patterns}

        predictions: list[dict[str, Any]] = []
        for sim in simulations:
            segment = sim.get("target_segment", "")
            pattern = pattern_map.get(segment, {})
            current_retention = round(1 - float(pattern.get("churn_rate", 0.1)), 3)
            change_pct = float(sim.get("predicted_retention_change", 0))
            predicted_retention = round(min(max(current_retention * (1 + change_pct / 100), 0), 1), 3)

            if predicted_retention < 0.7:
                risk = "high"
            elif predicted_retention < 0.85:
                risk = "moderate"
            else:
                risk = "low"

            predictions.append({
                "segment": segment,
                "action": sim.get("action", ""),
                "current_retention": current_retention,
                "predicted_retention": predicted_retention,
                "change_pct": change_pct,
                "risk_level": risk,
            })

        return {"status": "success", "predictions": predictions}
    except Exception as exc:
        return {"status": "error", "predictions": [], "error": f"Retention prediction failed: {exc}"}
