"""Price sensitivity decision logic — optimal pricing and impact modeling.

Provides:
  - calculate_optimal_price: find revenue- or profit-maximizing price
  - model_price_change_impact: what happens if we change price by X%?
  - find_price_ceiling: maximum willingness-to-pay analysis
"""
from __future__ import annotations

import math
from typing import Any

from .data import CATEGORY_ELASTICITY, WILLINGNESS_TO_PAY


def calculate_optimal_price(
    elasticity: float,
    unit_cost: float,
    current_price: float = 0.0,
    current_units: int = 100,
    target: str = "profit",
) -> dict[str, Any]:
    """Calculate the price that maximizes revenue or profit.

    For max profit with constant elasticity:
        optimal_price = unit_cost * elasticity / (1 + elasticity)
    (works when elasticity < -1)

    For max revenue with constant elasticity:
        Revenue is maximized at the boundary of the elastic range.

    Args:
        elasticity: Price elasticity (negative number).
        unit_cost: Cost per unit (COGS).
        current_price: Current selling price (for comparison).
        current_units: Current daily units sold.
        target: "profit" or "revenue".
    """
    abs_e = abs(elasticity)

    # Profit-optimal price (Lerner index approach)
    if abs_e > 1.0:
        optimal_profit_price = unit_cost * abs_e / (abs_e - 1.0)
    else:
        # Inelastic demand — profit increases with price, capped at practical limit
        optimal_profit_price = current_price * 1.25 if current_price > 0 else unit_cost * 4

    # Revenue-optimal price (set marginal revenue = 0)
    if abs_e > 1.0 and current_price > 0:
        # Revenue max is at price where |e| = 1 from current position
        revenue_max_price = current_price * (abs_e / (abs_e - 0.5))
        revenue_max_price = min(revenue_max_price, current_price * 1.5)
    else:
        revenue_max_price = current_price * 1.15 if current_price > 0 else unit_cost * 3

    chosen_price = optimal_profit_price if target == "profit" else revenue_max_price

    # Ensure price covers cost with minimum margin
    min_price = unit_cost * 1.20  # At least 20% margin
    chosen_price = max(chosen_price, min_price)

    # Project units at optimal price
    if current_price > 0 and current_units > 0:
        pct_change = (chosen_price - current_price) / current_price
        demand_change = elasticity * pct_change
        projected_units = max(1, current_units * (1 + demand_change))
    else:
        projected_units = current_units

    projected_revenue = chosen_price * projected_units
    projected_profit = (chosen_price - unit_cost) * projected_units

    return {
        "optimal_price": round(chosen_price, 2),
        "target": target,
        "projected_daily_units": round(projected_units, 1),
        "projected_daily_revenue": round(projected_revenue, 2),
        "projected_daily_profit": round(projected_profit, 2),
        "margin_pct": round((chosen_price - unit_cost) / chosen_price * 100, 1),
        "price_change_from_current": round(
            ((chosen_price - current_price) / current_price * 100) if current_price > 0 else 0, 1
        ),
        "optimal_profit_price": round(optimal_profit_price, 2),
        "optimal_revenue_price": round(revenue_max_price, 2),
    }


def model_price_change_impact(
    current_price: float,
    new_price: float,
    elasticity: float,
    current_daily_units: int = 100,
    unit_cost: float = 0.0,
) -> dict[str, Any]:
    """Model the demand and revenue impact of a specific price change.

    Args:
        current_price: Current selling price.
        new_price: Proposed new price.
        elasticity: Price elasticity (negative).
        current_daily_units: Current daily unit sales.
        unit_cost: Cost per unit (for profit calculation).
    """
    if current_price <= 0:
        return {"error": "Current price must be positive"}

    pct_price_change = (new_price - current_price) / current_price
    pct_demand_change = elasticity * pct_price_change
    new_units = max(0, current_daily_units * (1 + pct_demand_change))

    current_revenue = current_price * current_daily_units
    new_revenue = new_price * new_units

    current_profit = (current_price - unit_cost) * current_daily_units if unit_cost else 0
    new_profit = (new_price - unit_cost) * new_units if unit_cost else 0

    return {
        "current_price": current_price,
        "new_price": new_price,
        "price_change_pct": round(pct_price_change * 100, 1),
        "demand_change_pct": round(pct_demand_change * 100, 1),
        "current_daily_units": current_daily_units,
        "new_daily_units": round(new_units, 1),
        "current_daily_revenue": round(current_revenue, 2),
        "new_daily_revenue": round(new_revenue, 2),
        "revenue_change_pct": round((new_revenue - current_revenue) / current_revenue * 100, 1),
        "current_daily_profit": round(current_profit, 2),
        "new_daily_profit": round(new_profit, 2),
        "verdict": _price_change_verdict(current_revenue, new_revenue, current_profit, new_profit),
    }


def find_price_ceiling(
    willingness_data: dict[str, Any] | None = None,
    category: str = "general",
    current_price: float = 0.0,
) -> dict[str, Any]:
    """Find the maximum price the market will bear (price ceiling).

    Uses willingness-to-pay distribution data to find the price at which
    demand drops to near zero.

    Args:
        willingness_data: Custom WTP distribution, or None to use category defaults.
        category: Product category for default WTP lookup.
        current_price: Current price for context.
    """
    cat = category.lower().replace(" ", "_").replace("-", "_")
    wtp = willingness_data or WILLINGNESS_TO_PAY.get(cat, WILLINGNESS_TO_PAY["general"])

    percentiles = wtp.get("percentiles", {})
    median_wtp = percentiles.get("p50", current_price)
    ceiling_wtp = percentiles.get("p90", current_price * 2)
    floor_wtp = percentiles.get("p10", current_price * 0.5)

    # Price ceiling is roughly p75 — 75% of customers willing to pay this or less
    practical_ceiling = percentiles.get("p75", current_price * 1.3)

    return {
        "price_ceiling": round(practical_ceiling, 2),
        "absolute_maximum": round(ceiling_wtp, 2),
        "median_willingness": round(median_wtp, 2),
        "price_floor": round(floor_wtp, 2),
        "current_price_vs_median": (
            "above" if current_price > median_wtp else
            "below" if current_price < median_wtp * 0.9 else
            "at_market"
        ) if current_price > 0 else "unknown",
        "recommendation": _ceiling_recommendation(current_price, practical_ceiling, median_wtp),
        "distribution": percentiles,
    }


def _price_change_verdict(
    current_rev: float, new_rev: float, current_profit: float, new_profit: float
) -> str:
    """Summarize whether a price change is beneficial."""
    rev_better = new_rev > current_rev
    profit_better = new_profit > current_profit if current_profit else rev_better

    if rev_better and profit_better:
        return "Win-win: both revenue and profit improve"
    if profit_better and not rev_better:
        return "Profit improves but revenue drops — acceptable if margin-focused"
    if rev_better and not profit_better:
        return "Revenue grows but profit drops — not sustainable long-term"
    return "Both revenue and profit decline — avoid this price change"


def _ceiling_recommendation(current: float, ceiling: float, median: float) -> str:
    """Recommend pricing action based on WTP analysis."""
    if current <= 0:
        return f"Set initial price near ${median:.2f} (market median)"
    if current > ceiling:
        return "Price is above practical ceiling — expect significant demand loss"
    if current > median * 1.1:
        return "Price is above median WTP — consider lowering or adding perceived value"
    if current < median * 0.8:
        return "Price is well below market median — room to raise prices"
    return "Price is near market median — well-positioned"
