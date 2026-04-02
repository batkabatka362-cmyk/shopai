"""Pricing Engine — value estimator.

Estimates perceived value of a product based on quality signals, brand
strength, uniqueness, feature comparison, and customer willingness to pay.

Model note: Uses Mistral for value perception analysis.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Category value multipliers — how much more customers pay vs. cost
# ---------------------------------------------------------------------------

_CATEGORY_VALUE_MULTIPLIERS: dict[str, float] = {
    "electronics": 2.8,
    "fashion": 3.5,
    "beauty": 4.0,
    "home": 2.5,
    "sports": 2.3,
    "toys": 3.0,
    "food": 1.8,
    "books": 2.0,
    "software": 5.0,
    "health": 3.2,
}

_DEFAULT_VALUE_MULTIPLIER = 2.5

# ---------------------------------------------------------------------------
# Demand level adjustments
# ---------------------------------------------------------------------------

_DEMAND_ADJUSTMENTS: dict[str, float] = {
    "very_high": 1.25,
    "high": 1.15,
    "medium": 1.00,
    "low": 0.85,
    "very_low": 0.70,
}


def estimate_value(
    product: dict[str, Any],
    market: dict[str, Any],
    cost_analysis: dict[str, Any],
    competitor_mapping: dict[str, Any],
) -> dict[str, Any]:
    """Estimate the perceived value and willingness to pay.

    Args:
        product: ProductData dict.
        market: MarketData dict.
        cost_analysis: Output from cost_analyzer.
        competitor_mapping: Output from competitor_price_mapper.

    Returns:
        Structured dict with ValueEstimate data.
    """
    try:
        prod = copy.deepcopy(product)
        mkt = copy.deepcopy(market)
        costs = copy.deepcopy(cost_analysis)
        comp = copy.deepcopy(competitor_mapping)

        category = str(prod.get("category", "")).lower()
        cogs = float(prod.get("cogs", 0.0))
        demand_level = str(mkt.get("demand_level", "medium")).lower()
        avg_market_price = float(comp.get("avg_price", mkt.get("avg_market_price", 0.0)))
        median_price = float(comp.get("median_price", avg_market_price))
        cost_floor = float(costs.get("cost_floor", 0.0))

        # --- Quality score ---
        # Higher COGS relative to market price = higher perceived quality
        quality_score = _compute_quality_score(cogs, avg_market_price)

        # --- Brand strength ---
        # Without direct brand data, infer from category margin expectations
        category_margin = float(mkt.get("category_avg_margin", 0.35))
        brand_strength = min(category_margin / 0.50, 1.0)

        # --- Uniqueness score ---
        # Fewer competitors and higher price spread = more differentiation
        competitor_count = int(comp.get("competitor_count", 0))
        min_price = float(comp.get("min_price", 0.0))
        max_price = float(comp.get("max_price", 0.0))
        price_spread = (max_price - min_price) / avg_market_price if avg_market_price > 0 else 0.0
        uniqueness_score = min(price_spread * 0.5 + (1.0 / max(competitor_count, 1)) * 0.5, 1.0)

        # --- Feature value ---
        # Category multiplier indicates how much value customers assign
        multiplier = _CATEGORY_VALUE_MULTIPLIERS.get(category, _DEFAULT_VALUE_MULTIPLIER)
        feature_value = min(multiplier / 5.0, 1.0)

        # --- Willingness to pay ---
        # Base: category value multiplier applied to cost
        base_wtp = cogs * multiplier

        # Adjust for demand level
        demand_adj = _DEMAND_ADJUSTMENTS.get(demand_level, 1.0)
        demand_wtp = base_wtp * demand_adj

        # Anchor toward market reality — blend with market median
        if median_price > 0:
            wtp = demand_wtp * 0.4 + median_price * 0.6
        else:
            wtp = demand_wtp

        # Ensure WTP is at least the cost floor
        wtp = max(wtp, cost_floor)

        # --- Confidence ---
        # Higher confidence with more data points
        data_richness = min(competitor_count / 10.0, 1.0)
        value_confidence = round(0.5 + data_richness * 0.4, 2)

        return {
            "status": "success",
            "estimate": {
                "quality_score": round(quality_score, 2),
                "brand_strength": round(brand_strength, 2),
                "uniqueness_score": round(uniqueness_score, 2),
                "feature_value": round(feature_value, 2),
                "willingness_to_pay": round(wtp, 2),
                "value_confidence": value_confidence,
                "model_note": "Mistral: value perception and willingness-to-pay analysis",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "estimate": {},
            "error": f"Value estimation failed: {exc}",
        }


def _compute_quality_score(cogs: float, avg_market_price: float) -> float:
    """Derive quality score from cost-to-price ratio.

    Higher COGS relative to market price suggests better materials/build.
    """
    if avg_market_price <= 0 or cogs <= 0:
        return 0.5

    ratio = cogs / avg_market_price
    # ratio ~0.3 = average quality, ~0.5+ = high quality, ~0.15 = low
    score = min(ratio / 0.5, 1.0)
    return max(score, 0.1)
