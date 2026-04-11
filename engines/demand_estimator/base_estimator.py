"""Demand Estimator Engine — base estimator.

Estimate base demand from market size and product characteristics.
"""
from __future__ import annotations

import copy
from typing import Any


def estimate_base(
    **kwargs: Any,
) -> dict[str, Any]:
    """Estimate base demand.

    Args:
        **kwargs: Must include 'product', 'market_size'.

    Returns:
        Structured dict with base demand estimate.
    """
    try:
        product = copy.deepcopy(kwargs.get("product", {}))
        market_size = float(kwargs.get("market_size", 0))

        # Estimate capturable share based on product attributes
        quality_score = float(product.get("quality_score", 0.5))
        price_competitiveness = float(product.get("price_competitiveness", 0.5))
        brand_strength = float(product.get("brand_strength", 0.1))

        capture_rate = (quality_score * 0.4 + price_competitiveness * 0.35 + brand_strength * 0.25)
        capture_rate = round(min(capture_rate, 0.3), 4)  # Cap at 30% max

        base_demand = round(market_size * capture_rate)

        return {
            "status": "success",
            "result": {
                "base_demand": base_demand,
                "market_size": market_size,
                "capture_rate": capture_rate,
                "quality_factor": quality_score,
                "price_factor": price_competitiveness,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Base estimation failed: {exc}"}
