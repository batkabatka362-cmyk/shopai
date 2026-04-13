"""Pricing Engine — elasticity estimator.

Estimates price elasticity of demand: how sales volume changes with price.
Uses a log-linear demand model calibrated from competitor price data and
demand level to find the optimal price-volume tradeoff.

No dummy values — real elasticity math with demand curve modeling.
"""
from __future__ import annotations

import copy
import math
from typing import Any


# ---------------------------------------------------------------------------
# Base elasticity coefficients by category
# Elasticity < -1 = elastic (volume-sensitive), > -1 = inelastic
# ---------------------------------------------------------------------------

_CATEGORY_ELASTICITY: dict[str, float] = {
    "electronics": -1.8,
    "fashion": -2.2,
    "beauty": -1.5,
    "home": -1.3,
    "sports": -1.6,
    "toys": -2.0,
    "food": -0.8,
    "books": -1.1,
    "software": -1.0,
    "health": -0.7,
}

_DEFAULT_ELASTICITY = -1.5

# Demand level modifiers (higher demand = less elastic)
_DEMAND_ELASTICITY_MODIFIER: dict[str, float] = {
    "very_high": 0.30,   # less elastic (add toward 0)
    "high": 0.15,
    "medium": 0.0,
    "low": -0.20,         # more elastic (push further negative)
    "very_low": -0.40,
}


def estimate_elasticity(
    proposed_price: float,
    cost_analysis: dict[str, Any],
    competitor_mapping: dict[str, Any],
    product: dict[str, Any],
    market: dict[str, Any],
) -> dict[str, Any]:
    """Estimate price elasticity and optimal price-volume tradeoff.

    Args:
        proposed_price: The price under evaluation.
        cost_analysis: CostAnalysis from cost_analyzer.
        competitor_mapping: CompetitorPrices from competitor_price_mapper.
        product: ProductData dict.
        market: MarketData dict.

    Returns:
        Structured dict with ElasticityEstimate data.
    """
    try:
        costs = copy.deepcopy(cost_analysis)
        comp = copy.deepcopy(competitor_mapping)
        prod = copy.deepcopy(product)
        mkt = copy.deepcopy(market)

        price = float(proposed_price)
        cost_floor = float(costs.get("cost_floor", 0.0))
        total_cost = float(costs.get("total_cost", 0.0))
        avg_price = float(comp.get("avg_price", 0.0))
        category = str(prod.get("category", "")).lower()
        demand_level = str(mkt.get("demand_level", "medium")).lower()

        # --- Compute elasticity coefficient ---
        base_elasticity = _CATEGORY_ELASTICITY.get(category, _DEFAULT_ELASTICITY)
        demand_mod = _DEMAND_ELASTICITY_MODIFIER.get(demand_level, 0.0)
        elasticity = base_elasticity + demand_mod

        # --- Sensitivity label ---
        sensitivity = _classify_sensitivity(elasticity)

        # --- Price-volume curve ---
        # Model: Q(p) = Q_ref * (p / p_ref) ^ elasticity
        # Using avg market price as p_ref and normalized Q_ref = 100
        ref_price = avg_price if avg_price > 0 else price
        curve = _build_price_volume_curve(
            ref_price, elasticity, cost_floor, total_cost,
        )

        # --- Revenue-maximizing price ---
        # For log-linear demand: revenue R = p * Q_ref * (p/p_ref)^e
        # dR/dp = 0 => optimal p = p_ref * (-e / (1 + e))  when e < -1
        # For inelastic demand (e > -1), revenue increases with price
        if elasticity < -1.0:
            rev_max_price = ref_price * (elasticity / (1.0 + elasticity)) * -1.0
        else:
            # Inelastic: revenue increases with price up to ceiling
            rev_max_price = ref_price * 1.5

        rev_max_price = max(rev_max_price, cost_floor)
        rev_max_price = round(rev_max_price, 2)

        # --- Optimal volume-price (profit-maximizing) ---
        # profit = (p - total_cost) * Q(p)
        # Use numerical search over the curve
        optimal_volume_price = _find_profit_maximizing_price(
            ref_price, elasticity, total_cost, cost_floor,
        )

        return {
            "status": "success",
            "elasticity": {
                "elasticity_coefficient": round(elasticity, 2),
                "sensitivity": sensitivity,
                "optimal_volume_price": round(optimal_volume_price, 2),
                "price_volume_curve": curve,
                "revenue_maximizing_price": rev_max_price,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "elasticity": {},
            "error": f"Elasticity estimation failed: {exc}",
        }


def _classify_sensitivity(elasticity: float) -> str:
    """Classify price sensitivity based on elasticity coefficient."""
    abs_e = abs(elasticity)
    if abs_e < 0.5:
        return "very_low"
    if abs_e < 1.0:
        return "low"
    if abs_e < 1.5:
        return "medium"
    if abs_e < 2.5:
        return "high"
    return "very_high"


def _build_price_volume_curve(
    ref_price: float,
    elasticity: float,
    cost_floor: float,
    total_cost: float,
) -> list[dict[str, float]]:
    """Build a price-volume-profit curve at discrete price points.

    Generates 7 points spanning from cost_floor to 1.5x ref_price.
    """
    if ref_price <= 0:
        return []

    lo = max(cost_floor, ref_price * 0.5)
    hi = ref_price * 1.5
    if hi <= lo:
        hi = lo * 2.0

    step = (hi - lo) / 6.0
    curve: list[dict[str, float]] = []

    for i in range(7):
        p = lo + i * step
        if p <= 0:
            continue
        # Q = 100 * (p / ref_price) ^ elasticity
        volume = 100.0 * math.pow(p / ref_price, elasticity)
        revenue = p * volume
        profit = (p - total_cost) * volume

        curve.append({
            "price": round(p, 2),
            "relative_volume": round(volume, 1),
            "relative_revenue": round(revenue, 2),
            "relative_profit": round(profit, 2),
        })

    return curve


def _find_profit_maximizing_price(
    ref_price: float,
    elasticity: float,
    total_cost: float,
    cost_floor: float,
) -> float:
    """Numerically find the profit-maximizing price.

    Searches 50 price points between cost_floor and 2x ref_price.
    profit(p) = (p - total_cost) * 100 * (p / ref_price)^elasticity
    """
    if ref_price <= 0:
        return cost_floor

    lo = max(cost_floor, ref_price * 0.3)
    hi = ref_price * 2.0
    if hi <= lo:
        hi = lo * 2.0

    best_price = lo
    best_profit = -float("inf")

    steps = 50
    step = (hi - lo) / steps

    for i in range(steps + 1):
        p = lo + i * step
        if p <= 0:
            continue
        volume = 100.0 * math.pow(p / ref_price, elasticity)
        profit = (p - total_cost) * volume
        if profit > best_profit:
            best_profit = profit
            best_price = p

    return round(best_price, 2)
