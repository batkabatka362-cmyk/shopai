"""Demand Analysis Engine — volume estimator.

Estimate total demand volume from market data and product signals.
"""
from __future__ import annotations

import copy
from typing import Any


def estimate_volume(
    **kwargs: Any,
) -> dict[str, Any]:
    """Estimate demand volume.

    Args:
        **kwargs: Must include 'market_data' dict and 'products' list.

    Returns:
        Structured dict with volume estimation.
    """
    try:
        market_data = copy.deepcopy(kwargs.get("market_data", {}))
        products = kwargs.get("products", [])

        total_market_volume = int(market_data.get("total_volume", 0))
        our_volume = sum(int(p.get("units_sold_30d", 0)) for p in products)
        market_share_pct = round(our_volume / max(total_market_volume, 1) * 100, 2)

        # Growth estimation from historical data
        prev_volume = int(market_data.get("prev_period_volume", total_market_volume))
        if prev_volume > 0:
            growth_rate = round((total_market_volume - prev_volume) / prev_volume * 100, 1)
        else:
            growth_rate = 0.0

        return {
            "status": "success",
            "result": {
                "total_market_volume": total_market_volume,
                "our_volume": our_volume,
                "market_share_pct": market_share_pct,
                "growth_rate": growth_rate,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Volume estimation failed: {exc}"}
