"""Simulation Lab — performance estimator.

Estimates performance metrics for each scenario: expected revenue,
profit, ROI, margin, growth potential, scalability, time-to-breakeven.

Model note: Would use Qwen for structured performance metric output.
"""
from __future__ import annotations

import copy
import math
from typing import Any


def estimate_performance(
    simulation_results: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
    environment_factors: dict[str, Any],
) -> dict[str, Any]:
    """Estimate performance metrics for every scenario.

    Args:
        simulation_results: List of SimulationResult dicts.
        predictions: List of OutcomePrediction dicts.
        scenarios: Original scenario dicts.
        environment_factors: EnvironmentFactors for context.

    Returns:
        Structured dict with a PerformanceEstimate per scenario.
    """
    try:
        sim_results = copy.deepcopy(simulation_results)
        pred_map = {p["scenario_id"]: p for p in copy.deepcopy(predictions)}
        scen_map = {s["scenario_id"]: s for s in copy.deepcopy(scenarios)}
        env = copy.deepcopy(environment_factors)

        estimates: list[dict[str, Any]] = []
        for result in sim_results:
            sid = result.get("scenario_id", "unknown")
            pred = pred_map.get(sid, {})
            scenario = scen_map.get(sid, {})
            est = _estimate_single(result, pred, scenario, env)
            estimates.append(est)

        return {
            "status": "success",
            "estimates": estimates,
            "count": len(estimates),
        }
    except Exception as exc:
        return {
            "status": "error",
            "estimates": [],
            "count": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Single-scenario performance estimation
# ---------------------------------------------------------------------------

def _estimate_single(
    result: dict[str, Any],
    prediction: dict[str, Any],
    scenario: dict[str, Any],
    env: dict[str, Any],
) -> dict[str, Any]:
    """Estimate performance for one scenario."""
    sid = result.get("scenario_id", "unknown")
    params = scenario.get("parameters", {})

    mean_rev = float(result.get("mean_revenue", 0.0))
    mean_profit = float(result.get("mean_profit", 0.0))
    mean_cost = float(result.get("mean_cost", 0.0))
    mean_margin = float(result.get("mean_margin", 0.0))
    std_rev = float(result.get("std_revenue", 0.0))

    predicted_roi = float(prediction.get("predicted_roi", 0.0))
    predicted_risk = float(prediction.get("predicted_risk", 0.5))

    maturity_mod = float(env.get("maturity_modifier", 1.0))
    demand_elast = float(env.get("demand_elasticity", 1.0))

    # Expected values: blend of mean and p50 for robustness
    expected_revenue = round(
        mean_rev * 0.4 + float(result.get("revenue_p50", mean_rev)) * 0.6, 2
    )
    expected_profit = round(
        mean_profit * 0.4 + float(result.get("profit_p50", mean_profit)) * 0.6, 2
    )
    expected_roi = round(predicted_roi, 4)
    expected_margin = round(mean_margin, 4)

    # Growth potential: based on demand trend, margin headroom, variation type
    growth_base = 0.5
    if demand_elast > 1.0:
        growth_base += (demand_elast - 1.0) * 1.5
    if mean_margin > 0.25:
        growth_base += 0.1
    if scenario.get("variation_type") == "aggressive":
        growth_base += 0.1
    elif scenario.get("variation_type") == "conservative":
        growth_base -= 0.1
    growth_potential = round(max(0.0, min(1.0, growth_base)), 4)

    # Scalability score: based on margin sustainability, cost structure, maturity
    scalability_base = 0.5
    if mean_margin > 0.20:
        scalability_base += 0.15
    if maturity_mod >= 1.0:
        scalability_base += 0.10
    # Low variance = more scalable
    cv_rev = (std_rev / mean_rev) if mean_rev > 0 else 1.0
    if cv_rev < 0.20:
        scalability_base += 0.10
    elif cv_rev > 0.40:
        scalability_base -= 0.15
    # Risk penalty
    scalability_base -= predicted_risk * 0.15
    scalability_score = round(max(0.0, min(1.0, scalability_base)), 4)

    # Time to breakeven (days): initial investment / daily profit
    initial_investment = float(params.get("ad_spend", params.get("marketing_budget", 0.0)))
    initial_investment += float(params.get("initial_cost", params.get("setup_cost", 0.0)))
    # Assume simulation represents a 30-day period
    daily_profit = expected_profit / 30.0 if expected_profit != 0 else 0.0
    if daily_profit > 0 and initial_investment > 0:
        breakeven_days = round(initial_investment / daily_profit, 1)
    elif expected_profit > 0 and initial_investment == 0:
        breakeven_days = 0.0  # No upfront investment
    else:
        breakeven_days = -1.0  # Never breaks even (signal value)

    return {
        "scenario_id": sid,
        "expected_revenue": expected_revenue,
        "expected_profit": expected_profit,
        "expected_roi": expected_roi,
        "expected_margin": expected_margin,
        "growth_potential": growth_potential,
        "scalability_score": scalability_score,
        "time_to_breakeven_days": breakeven_days,
    }
