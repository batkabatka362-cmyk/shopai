"""Dynamic Pricing Engine — signal collector.

Collects and normalizes all market signals for each product:
demand velocity, competitor price changes, inventory levels, time factors.

1 file = 1 job: collect and normalize raw inputs into structured signals.
"""
from __future__ import annotations

import copy
from typing import Any


def collect_signals(
    product: dict[str, Any],
    market_signals: dict[str, Any],
) -> dict[str, Any]:
    """Collect and normalize signals for a single product.

    Args:
        product: ProductInput dict with id, current_price, cogs, daily_sales.
        market_signals: MarketSignals dict with demand_index, competitor_prices,
                        inventory_days, season.

    Returns:
        Structured dict with CollectedSignals data.
    """
    try:
        prod = copy.deepcopy(product)
        signals = copy.deepcopy(market_signals)

        product_id = str(prod.get("id", "unknown"))
        current_price = float(prod.get("current_price", 0.0))
        cogs = float(prod.get("cogs", 0.0))
        daily_sales = float(prod.get("daily_sales", 0.0))

        # Demand index: 1.0 = normal, >1 = above normal, <1 = below
        demand_index = float(signals.get("demand_index", 1.0))
        demand_index = max(demand_index, 0.0)

        # Competitor prices: accept dict (name->price) or list
        raw_competitor = signals.get("competitor_prices", {})
        if isinstance(raw_competitor, dict):
            competitor_prices = [
                float(p) for p in raw_competitor.values() if _is_numeric(p)
            ]
        elif isinstance(raw_competitor, list):
            competitor_prices = [float(p) for p in raw_competitor if _is_numeric(p)]
        else:
            competitor_prices = []

        # Inventory days of stock
        inventory_days = float(signals.get("inventory_days", 30.0))
        inventory_days = max(inventory_days, 0.0)

        # Season
        season = str(signals.get("season", "normal")).lower()

        return {
            "status": "success",
            "signals": {
                "product_id": product_id,
                "current_price": round(current_price, 2),
                "cogs": round(cogs, 2),
                "daily_sales": round(daily_sales, 2),
                "demand_index": round(demand_index, 3),
                "competitor_prices": [round(p, 2) for p in competitor_prices],
                "inventory_days": round(inventory_days, 1),
                "season": season,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "signals": {},
            "error": f"Signal collection failed: {exc}",
        }


def _is_numeric(value: Any) -> bool:
    """Check if a value can be cast to float."""
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
