"""Market Simulator Engine — demand modeler.

Models demand response curves based on product data and market conditions.
Calculates price elasticity and marketing sensitivity.
"""
from __future__ import annotations

import copy
from typing import Any


def model_demand(
    product: dict[str, Any],
    market_data: dict[str, Any],
) -> dict[str, Any]:
    """Model demand response curves for a product."""
    try:
        product = copy.deepcopy(product)
        market_data = copy.deepcopy(market_data)

        base_price = float(product.get("price", 0.0))
        base_units = float(product.get("monthly_units", 0.0))
        category = str(product.get("category", "general"))

        elasticity_map = {
            "luxury": -0.5, "premium": -0.8, "general": -1.2,
            "commodity": -1.8, "essential": -0.3,
        }
        price_elasticity = elasticity_map.get(category, -1.2)

        market_size = float(market_data.get("market_size", 100000))
        current_share = float(market_data.get("market_share", 0.01))
        marketing_sensitivity = round(base_units * 0.05 * (1 - current_share), 2)

        demand_curve = []
        for pct in range(-30, 35, 5):
            demand_change = round(pct * price_elasticity / 100.0, 4)
            new_demand = round(base_units * (1 + demand_change), 1)
            new_revenue = round(new_demand * base_price * (1 + pct / 100.0), 2)
            demand_curve.append({
                "price_change_pct": pct,
                "demand_change_pct": round(demand_change * 100, 2),
                "predicted_units": max(new_demand, 0),
                "predicted_revenue": max(new_revenue, 0),
            })

        confidence = 0.75
        if base_units > 100:
            confidence = min(confidence + 0.1, 0.95)
        if market_data.get("historical_months", 0) > 6:
            confidence = min(confidence + 0.1, 0.95)

        return {
            "status": "success",
            "demand_model": {
                "product_id": str(product.get("id", "")),
                "base_demand": base_units,
                "price_elasticity": price_elasticity,
                "marketing_sensitivity": marketing_sensitivity,
                "demand_curve": demand_curve,
                "confidence": round(confidence, 2),
            },
        }
    except Exception as exc:
        return {"status": "error", "demand_model": {}, "error": f"Demand modeling failed: {exc}"}
