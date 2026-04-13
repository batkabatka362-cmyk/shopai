"""Price sensitivity analysis — how price changes affect demand volume.

Core concepts:
  Price elasticity of demand (PED):
    PED = (% change in quantity demanded) / (% change in price)
    - |PED| < 1: inelastic (necessities) — raise prices for more revenue
    - |PED| = 1: unit elastic — revenue stays constant
    - |PED| > 1: elastic (luxuries, commodities) — lower prices for more revenue

  Optimal pricing:
    - Max revenue: where marginal revenue = 0
    - Max profit: where marginal profit = 0 (accounts for costs)
"""
from __future__ import annotations

from typing import Any

from .data import (
    CATEGORY_ELASTICITY,
    SEGMENT_ELASTICITY_MULTIPLIERS,
    COMPETITOR_PRICE_IMPACT,
    WILLINGNESS_TO_PAY,
)


def analyze_price_sensitivity(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Analyze how price changes would affect demand for a product.

    Args:
        input_payload: {
            "category": str,
            "current_price": float,
            "unit_cost": float,             # COGS per unit
            "current_daily_units": int,
            "competitor_avg_price": float,   # Average competitor price
            "customer_segment": str,         # "price_conscious", "mid_market", "premium"
            "brand_strength": float,         # 0.0 - 1.0 (strong brand = less elastic)
        }

    Returns:
        Elasticity estimate, optimal prices, and demand projections.
    """
    category = input_payload.get("category", "general")
    current_price = input_payload.get("current_price", 30.0)
    unit_cost = input_payload.get("unit_cost", 10.0)
    daily_units = input_payload.get("current_daily_units", 10)
    competitor_price = input_payload.get("competitor_avg_price", current_price)
    segment = input_payload.get("customer_segment", "mid_market")
    brand_strength = input_payload.get("brand_strength", 0.3)

    # Calculate effective elasticity
    base_elasticity = _get_base_elasticity(category)
    segment_mult = SEGMENT_ELASTICITY_MULTIPLIERS.get(segment, 1.0)
    brand_reduction = brand_strength * 0.4  # Strong brand reduces elasticity up to 40%
    elasticity = base_elasticity * segment_mult * (1.0 - brand_reduction)

    # Price position relative to competitors
    price_ratio = current_price / competitor_price if competitor_price > 0 else 1.0

    # Revenue and profit curves at different price points
    revenue_curve = estimate_revenue_curve(current_price, daily_units, elasticity)
    profit_curve = estimate_profit_curve(current_price, daily_units, unit_cost, elasticity)

    # Optimal prices
    optimal_revenue_price = _find_optimal(revenue_curve, "daily_revenue")
    optimal_profit_price = _find_optimal(profit_curve, "daily_profit")

    return {
        "elasticity": round(elasticity, 2),
        "elasticity_interpretation": _interpret_elasticity(elasticity),
        "current_price": current_price,
        "current_daily_revenue": round(current_price * daily_units, 2),
        "current_daily_profit": round((current_price - unit_cost) * daily_units, 2),
        "competitor_price_ratio": round(price_ratio, 2),
        "optimal_price_for_revenue": optimal_revenue_price,
        "optimal_price_for_profit": optimal_profit_price,
        "revenue_curve": revenue_curve[:7],  # Sample points
        "profit_curve": profit_curve[:7],
        "modifiers": {
            "base_elasticity": round(base_elasticity, 2),
            "segment_multiplier": round(segment_mult, 2),
            "brand_reduction": round(brand_reduction, 2),
        },
        "input": input_payload,
    }


def estimate_revenue_curve(
    current_price: float,
    current_units: int,
    elasticity: float,
    steps: int = 11,
) -> list[dict[str, Any]]:
    """Generate revenue at different price points.

    Tests prices from -30% to +30% of current price.
    """
    results = []
    for i in range(steps):
        pct_change = -0.30 + (i * 0.06)  # -30% to +30%
        new_price = current_price * (1 + pct_change)
        if new_price <= 0:
            continue
        demand_change = elasticity * pct_change  # Elasticity is negative
        new_units = max(0, current_units * (1 + demand_change))
        revenue = new_price * new_units

        results.append({
            "price": round(new_price, 2),
            "price_change_pct": round(pct_change * 100, 1),
            "estimated_daily_units": round(new_units, 1),
            "daily_revenue": round(revenue, 2),
        })

    return results


def estimate_profit_curve(
    current_price: float,
    current_units: int,
    unit_cost: float,
    elasticity: float,
    steps: int = 11,
) -> list[dict[str, Any]]:
    """Generate profit at different price points."""
    results = []
    for i in range(steps):
        pct_change = -0.30 + (i * 0.06)
        new_price = current_price * (1 + pct_change)
        if new_price <= unit_cost:
            continue
        demand_change = elasticity * pct_change
        new_units = max(0, current_units * (1 + demand_change))
        profit = (new_price - unit_cost) * new_units

        results.append({
            "price": round(new_price, 2),
            "price_change_pct": round(pct_change * 100, 1),
            "estimated_daily_units": round(new_units, 1),
            "daily_profit": round(profit, 2),
            "margin_pct": round((new_price - unit_cost) / new_price * 100, 1),
        })

    return results


def _get_base_elasticity(category: str) -> float:
    """Look up base price elasticity for a category."""
    cat = category.lower().replace(" ", "_").replace("-", "_")
    if cat in CATEGORY_ELASTICITY:
        return CATEGORY_ELASTICITY[cat]
    for key in CATEGORY_ELASTICITY:
        if key in cat or cat in key:
            return CATEGORY_ELASTICITY[key]
    return -1.0  # Default unit elastic


def _interpret_elasticity(elasticity: float) -> str:
    """Human-readable interpretation of price elasticity."""
    abs_e = abs(elasticity)
    if abs_e < 0.5:
        return "Highly inelastic — customers barely react to price changes. Consider raising prices."
    if abs_e < 1.0:
        return "Inelastic — demand drops slower than price rises. Raising prices increases revenue."
    if abs_e < 1.2:
        return "Near unit elastic — revenue roughly constant across price changes."
    if abs_e < 2.0:
        return "Elastic — demand is sensitive to price. Small decreases can boost volume significantly."
    return "Highly elastic — demand is very price-sensitive. Compete on value, not price."


def _find_optimal(curve: list[dict[str, Any]], metric: str) -> float:
    """Find the price that maximizes a given metric in the curve."""
    if not curve:
        return 0.0
    best = max(curve, key=lambda p: p.get(metric, 0))
    return best["price"]
