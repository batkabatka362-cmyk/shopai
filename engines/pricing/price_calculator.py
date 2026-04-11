"""Pricing Engine — price calculator.

Calculates the optimal price using three strategies:
  1. Cost-plus: total_cost / (1 - target_margin)
  2. Competitive: market positioning relative to avg/median
  3. Value-based: willingness to pay from value estimator

Produces a weighted recommendation blending all three strategies.

All math is real — actual formulas, no dummy values.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Strategy weight profiles based on data availability and demand
# ---------------------------------------------------------------------------

_DEMAND_WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "very_high": {"cost_plus": 0.15, "competitive": 0.25, "value_based": 0.60},
    "high":      {"cost_plus": 0.20, "competitive": 0.30, "value_based": 0.50},
    "medium":    {"cost_plus": 0.30, "competitive": 0.40, "value_based": 0.30},
    "low":       {"cost_plus": 0.35, "competitive": 0.45, "value_based": 0.20},
    "very_low":  {"cost_plus": 0.45, "competitive": 0.40, "value_based": 0.15},
}

_DEFAULT_WEIGHTS = {"cost_plus": 0.30, "competitive": 0.40, "value_based": 0.30}


def calculate_prices(
    cost_analysis: dict[str, Any],
    competitor_mapping: dict[str, Any],
    value_estimate: dict[str, Any],
    target_margin: float,
    demand_level: str,
) -> dict[str, Any]:
    """Calculate optimal price using three pricing strategies.

    Args:
        cost_analysis: CostAnalysis from cost_analyzer.
        competitor_mapping: CompetitorPrices from competitor_price_mapper.
        value_estimate: ValueEstimate from value_estimator.
        target_margin: Desired profit margin as decimal (e.g. 0.40).
        demand_level: Current demand level string.

    Returns:
        Structured dict with PriceCalculation data.
    """
    try:
        costs = copy.deepcopy(cost_analysis)
        comp = copy.deepcopy(competitor_mapping)
        value = copy.deepcopy(value_estimate)

        cost_floor = float(costs.get("cost_floor", 0.0))
        total_cost = float(costs.get("total_cost", 0.0))
        avg_price = float(comp.get("avg_price", 0.0))
        median_price = float(comp.get("median_price", 0.0))
        wtp = float(value.get("willingness_to_pay", 0.0))
        margin = min(max(float(target_margin), 0.0), 0.99)

        # --- Strategy 1: Cost-plus ---
        # Price = total_cost / (1 - target_margin)
        if margin < 1.0:
            cost_plus_price = total_cost / (1.0 - margin)
        else:
            cost_plus_price = total_cost * 2.0  # fallback

        # --- Strategy 2: Competitive ---
        # Position at market average, weighted toward median for robustness
        if avg_price > 0 and median_price > 0:
            competitive_price = avg_price * 0.4 + median_price * 0.6
        elif avg_price > 0:
            competitive_price = avg_price
        else:
            competitive_price = cost_plus_price  # fall back to cost-plus

        # Ensure competitive price covers cost floor
        competitive_price = max(competitive_price, cost_floor)

        # --- Strategy 3: Value-based ---
        # Use willingness to pay directly, bounded by cost floor
        value_based_price = max(wtp, cost_floor)

        # --- Weighted blend ---
        demand = demand_level.lower() if demand_level else "medium"
        weights = _DEMAND_WEIGHT_PROFILES.get(demand, _DEFAULT_WEIGHTS)

        # Adjust weights if we lack competitor data
        if avg_price <= 0:
            weights = {
                "cost_plus": 0.50,
                "competitive": 0.0,
                "value_based": 0.50,
            }

        weighted_price = (
            cost_plus_price * weights["cost_plus"]
            + competitive_price * weights["competitive"]
            + value_based_price * weights["value_based"]
        )

        # Final price must be at least the cost floor
        weighted_price = max(weighted_price, cost_floor)

        # Determine dominant strategy
        recommended_strategy = max(weights, key=lambda k: weights[k])

        return {
            "status": "success",
            "calculation": {
                "cost_plus_price": round(cost_plus_price, 2),
                "competitive_price": round(competitive_price, 2),
                "value_based_price": round(value_based_price, 2),
                "weighted_price": round(weighted_price, 2),
                "strategy_weights": {k: round(v, 2) for k, v in weights.items()},
                "recommended_strategy": recommended_strategy,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "calculation": {},
            "error": f"Price calculation failed: {exc}",
        }
