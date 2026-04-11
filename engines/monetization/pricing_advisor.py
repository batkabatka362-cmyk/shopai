"""Monetization Engine — pricing advisor.

Advises on pricing models and strategies based on
product mix, competition, and demand elasticity.
"""
from __future__ import annotations

import copy
from typing import Any


def advise_pricing(
    products: list[dict[str, Any]],
    revenue_data: dict[str, Any],
) -> dict[str, Any]:
    """Advise on pricing models and strategies.

    Args:
        products: Product catalog.
        revenue_data: Revenue metrics.

    Returns:
        Structured dict with pricing recommendations.
    """
    try:
        prods = copy.deepcopy(products)
        recommendations: list[str] = []
        models: list[str] = []

        if not prods:
            return {
                "status": "success",
                "recommended_models": [],
                "recommendations": [],
                "projected_uplift_pct": 0.0,
            }

        # Analyze price distribution
        prices = [float(p.get("price", 0)) for p in prods if p.get("price")]
        if not prices:
            return {
                "status": "success",
                "recommended_models": ["cost_plus"],
                "recommendations": ["Add pricing data to products"],
                "projected_uplift_pct": 0.0,
            }

        avg_price = sum(prices) / len(prices)
        min_price = min(prices)
        max_price = max(prices)
        price_spread = max_price - min_price

        # Recommend tiered pricing if wide price spread
        if price_spread > avg_price * 2:
            models.append("tiered_pricing")
            recommendations.append("Wide price spread supports tiered pricing (good/better/best)")

        # Check margin distribution
        margins = []
        from utils.finance import margin as _margin
        for prod in prods:
            price = float(prod.get("price", 0))
            cost = float(prod.get("cost", prod.get("unit_cost", 0)))
            m = _margin(price, cost, default=-1.0)
            if m >= 0:
                margins.append(m)

        if margins:
            avg_margin = sum(margins) / len(margins)
            if avg_margin < 0.3:
                models.append("value_based_pricing")
                recommendations.append("Margins below 30% — consider value-based pricing")
            elif avg_margin > 0.6:
                models.append("competitive_pricing")
                recommendations.append("High margins — monitor competitive pricing pressure")

        # Subscription model if applicable
        consumables = sum(1 for p in prods if p.get("is_consumable", False))
        if consumables > len(prods) * 0.2:
            models.append("subscription")
            recommendations.append(f"{consumables} consumable products — subscription model viable")

        if not models:
            models.append("cost_plus")

        projected_uplift = 0.0
        if "value_based_pricing" in models:
            projected_uplift += 5.0
        if "tiered_pricing" in models:
            projected_uplift += 3.0
        if "subscription" in models:
            projected_uplift += 8.0

        return {
            "status": "success",
            "recommended_models": models,
            "recommendations": recommendations,
            "projected_uplift_pct": round(projected_uplift, 1),
        }
    except Exception as exc:
        return {
            "status": "error",
            "recommended_models": [],
            "error": f"Pricing advisory failed: {exc}",
        }
