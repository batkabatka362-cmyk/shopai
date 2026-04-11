"""Simulation Lab — simulation engine.

Runs Monte Carlo simulations for each scenario. Produces per-iteration
results and aggregated statistics (mean, std, percentiles).

Model note: Would use Mistral for validation of simulation parameters.
"""
from __future__ import annotations

import copy
import math
import random
from typing import Any


def run_simulations(
    scenarios: list[dict[str, Any]],
    environment_factors: dict[str, Any],
    iterations: int = 200,
) -> dict[str, Any]:
    """Run Monte Carlo simulations for every scenario.

    Each iteration samples random noise around the scenario parameters,
    applies environment modifiers, and computes revenue/profit/cost/margin.

    Args:
        scenarios: List of Scenario dicts from the scenario generator.
        environment_factors: EnvironmentFactors from the environment model.
        iterations: Number of Monte Carlo iterations per scenario.

    Returns:
        Structured dict with a SimulationResult per scenario.
    """
    try:
        scenarios = copy.deepcopy(scenarios)
        env = copy.deepcopy(environment_factors)
        iterations = max(1, min(iterations, 10_000))

        results: list[dict[str, Any]] = []
        for scenario in scenarios:
            sim_result = _simulate_scenario(scenario, env, iterations)
            results.append(sim_result)

        return {
            "status": "success",
            "results": results,
            "scenarios_run": len(results),
            "iterations_per_scenario": iterations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "results": [],
            "scenarios_run": 0,
            "iterations_per_scenario": iterations,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Core simulation logic
# ---------------------------------------------------------------------------

def _simulate_scenario(
    scenario: dict[str, Any],
    env: dict[str, Any],
    iterations: int,
) -> dict[str, Any]:
    """Run all iterations for a single scenario and aggregate."""
    params = scenario.get("parameters", {})
    scenario_id = scenario.get("scenario_id", "unknown")

    # Extract base values from parameters (with sensible defaults)
    base_price = _numeric(params.get("price", params.get("base_price", 25.0)))
    base_units = _numeric(params.get("units", params.get("volume", 100)))
    base_cost_per_unit = _numeric(params.get("cost", params.get("unit_cost", 10.0)))
    base_ad_spend = _numeric(params.get("ad_spend", params.get("marketing_budget", 0.0)))
    base_conversion = _numeric(params.get("conversion_rate", 0.03))

    combined_mod = _numeric(env.get("combined_modifier", 1.0))
    volatility = _numeric(env.get("volatility_factor", 0.15))

    raw_iterations: list[dict[str, Any]] = []

    for i in range(iterations):
        # Sample noise: Gaussian centered at 1.0, scaled by volatility
        demand_noise = max(0.1, random.gauss(1.0, volatility))
        price_noise = max(0.5, random.gauss(1.0, volatility * 0.3))
        cost_noise = max(0.5, random.gauss(1.0, volatility * 0.2))

        effective_price = base_price * price_noise
        effective_units = max(1, int(base_units * demand_noise * combined_mod))
        effective_cost = base_cost_per_unit * cost_noise

        # Conversion-adjusted units for ad-driven scenarios
        if base_ad_spend > 0 and base_conversion > 0:
            ad_driven = base_ad_spend / max(effective_price, 0.01) * base_conversion * demand_noise
            effective_units = max(1, int(effective_units + ad_driven))

        revenue = round(effective_price * effective_units, 2)
        total_cost = round(effective_cost * effective_units + base_ad_spend, 2)
        profit = round(revenue - total_cost, 2)
        margin = round(profit / revenue, 4) if revenue > 0 else 0.0

        raw_iterations.append({
            "iteration": i,
            "revenue": revenue,
            "profit": profit,
            "units_sold": effective_units,
            "cost": total_cost,
            "margin": margin,
        })

    return _aggregate(scenario_id, raw_iterations, iterations)


def _aggregate(
    scenario_id: str,
    raw: list[dict[str, Any]],
    iterations: int,
) -> dict[str, Any]:
    """Aggregate raw iteration results into summary statistics."""
    if not raw:
        return _empty_result(scenario_id, iterations)

    revenues = [r["revenue"] for r in raw]
    profits = [r["profit"] for r in raw]
    units = [r["units_sold"] for r in raw]
    costs = [r["cost"] for r in raw]
    margins = [r["margin"] for r in raw]

    return {
        "scenario_id": scenario_id,
        "iterations": iterations,
        "mean_revenue": round(_mean(revenues), 2),
        "mean_profit": round(_mean(profits), 2),
        "mean_units_sold": round(_mean(units), 2),
        "mean_cost": round(_mean(costs), 2),
        "mean_margin": round(_mean(margins), 4),
        "std_revenue": round(_std(revenues), 2),
        "std_profit": round(_std(profits), 2),
        "revenue_p5": round(_percentile(revenues, 5), 2),
        "revenue_p50": round(_percentile(revenues, 50), 2),
        "revenue_p95": round(_percentile(revenues, 95), 2),
        "profit_p5": round(_percentile(profits, 5), 2),
        "profit_p50": round(_percentile(profits, 50), 2),
        "profit_p95": round(_percentile(profits, 95), 2),
        "raw_iterations": raw,
    }


def _empty_result(scenario_id: str, iterations: int) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "iterations": iterations,
        "mean_revenue": 0.0,
        "mean_profit": 0.0,
        "mean_units_sold": 0.0,
        "mean_cost": 0.0,
        "mean_margin": 0.0,
        "std_revenue": 0.0,
        "std_profit": 0.0,
        "revenue_p5": 0.0,
        "revenue_p50": 0.0,
        "revenue_p95": 0.0,
        "profit_p5": 0.0,
        "profit_p50": 0.0,
        "profit_p95": 0.0,
        "raw_iterations": [],
    }


# ---------------------------------------------------------------------------
# Math helpers (no numpy dependency)
# ---------------------------------------------------------------------------

def _numeric(val: Any, default: float = 0.0) -> float:
    """Safely coerce to float."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    variance = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
    return math.sqrt(variance)


def _percentile(vals: list[float], pct: float) -> float:
    if not vals:
        return 0.0
    sorted_vals = sorted(vals)
    k = (pct / 100.0) * (len(sorted_vals) - 1)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    d = k - f
    return sorted_vals[f] + d * (sorted_vals[c] - sorted_vals[f])
