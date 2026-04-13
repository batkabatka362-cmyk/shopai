"""Simulation Lab — outcome predictor.

Predicts outcomes (revenue, profit, risk, ROI) from simulation results.
Combines statistical aggregates with environment-adjusted confidence bands.

Model note: Would use Mistral for analysis/validation of prediction quality.
"""
from __future__ import annotations

import copy
import math
from typing import Any


def predict_outcomes(
    simulation_results: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
    environment_factors: dict[str, Any],
) -> dict[str, Any]:
    """Predict outcomes for every simulated scenario.

    Merges simulation statistics with environment context to produce
    calibrated revenue/profit predictions with confidence intervals.

    Args:
        simulation_results: List of SimulationResult dicts.
        scenarios: Original scenario dicts (for parameter context).
        environment_factors: EnvironmentFactors for adjustment.

    Returns:
        Structured dict with an OutcomePrediction per scenario.
    """
    try:
        sim_results = copy.deepcopy(simulation_results)
        scen_map = {s["scenario_id"]: s for s in copy.deepcopy(scenarios)}
        env = copy.deepcopy(environment_factors)
        volatility = float(env.get("volatility_factor", 0.15))

        predictions: list[dict[str, Any]] = []
        for result in sim_results:
            pred = _predict_single(result, scen_map, volatility)
            predictions.append(pred)

        return {
            "status": "success",
            "predictions": predictions,
            "count": len(predictions),
        }
    except Exception as exc:
        return {
            "status": "error",
            "predictions": [],
            "count": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Single-scenario prediction
# ---------------------------------------------------------------------------

def _predict_single(
    result: dict[str, Any],
    scen_map: dict[str, dict[str, Any]],
    volatility: float,
) -> dict[str, Any]:
    """Compute outcome prediction for one scenario."""
    sid = result.get("scenario_id", "unknown")
    scenario = scen_map.get(sid, {})
    params = scenario.get("parameters", {})

    mean_rev = float(result.get("mean_revenue", 0.0))
    mean_profit = float(result.get("mean_profit", 0.0))
    std_rev = float(result.get("std_revenue", 0.0))
    std_profit = float(result.get("std_profit", 0.0))
    mean_cost = float(result.get("mean_cost", 0.0))

    # Predicted values: use median (p50) as primary predictor for robustness
    predicted_revenue = float(result.get("revenue_p50", mean_rev))
    predicted_profit = float(result.get("profit_p50", mean_profit))

    # ROI: profit relative to cost
    predicted_roi = (predicted_profit / mean_cost) if mean_cost > 0 else 0.0

    # Risk: coefficient of variation penalized by volatility
    cv_rev = (std_rev / mean_rev) if mean_rev > 0 else 1.0
    cv_profit = (std_profit / abs(mean_profit)) if mean_profit != 0 else 1.0
    base_risk = min(1.0, (cv_rev * 0.4 + cv_profit * 0.4 + volatility * 0.2))

    # Penalty for scenarios where p5 profit is negative
    p5_profit = float(result.get("profit_p5", 0.0))
    if p5_profit < 0:
        loss_severity = min(1.0, abs(p5_profit) / max(abs(predicted_profit), 1.0))
        base_risk = min(1.0, base_risk + loss_severity * 0.2)

    predicted_risk = round(base_risk, 4)

    # Revenue and profit confidence ranges (5th-95th percentile)
    rev_lo = float(result.get("revenue_p5", predicted_revenue * 0.7))
    rev_hi = float(result.get("revenue_p95", predicted_revenue * 1.3))
    prof_lo = float(result.get("profit_p5", predicted_profit * 0.7))
    prof_hi = float(result.get("profit_p95", predicted_profit * 1.3))

    # Confidence: inverse of risk, scaled
    confidence = round(max(0.0, min(1.0, 1.0 - predicted_risk * 0.8)), 4)

    return {
        "scenario_id": sid,
        "predicted_revenue": round(predicted_revenue, 2),
        "predicted_profit": round(predicted_profit, 2),
        "predicted_risk": predicted_risk,
        "predicted_roi": round(predicted_roi, 4),
        "revenue_range": [round(rev_lo, 2), round(rev_hi, 2)],
        "profit_range": [round(prof_lo, 2), round(prof_hi, 2)],
        "confidence": confidence,
    }
