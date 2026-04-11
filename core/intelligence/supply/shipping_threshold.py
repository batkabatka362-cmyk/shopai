"""Shipping threshold optimization — AOV * 1.3 formula."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float

logger = get_logger("intelligence.supply.shipping_threshold")


def optimize_shipping_threshold(
    products: list[dict[str, Any]],
    orders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Calculate optimal free shipping threshold.

    Formula: AOV * 1.3 = optimal threshold
    This turns shipping from a cost into a marketing tool that increases AOV.
    """
    order_values = []
    if orders:
        order_values = [safe_float(o.get("total", 0)) for o in orders if isinstance(o, dict) and safe_float(o.get("total", 0)) > 0]

    if not order_values:
        prices = [safe_float(p.get("price", 0)) for p in products if isinstance(p, dict)]
        avg_price = sum(prices) / max(len(prices), 1)
        order_values = [avg_price]

    current_aov = round(sum(order_values) / len(order_values), 2)
    optimal_threshold = round(current_aov * 1.3, 2)

    # Round to nearest $5 for clean pricing
    optimal_threshold = round(optimal_threshold / 5) * 5

    # Estimate impact
    orders_below = sum(1 for v in order_values if v < optimal_threshold)
    pct_below = round(orders_below / max(len(order_values), 1) * 100, 1)

    return {
        "current_aov": current_aov,
        "recommended_threshold": optimal_threshold,
        "formula": "AOV × 1.3, rounded to nearest $5",
        "orders_below_threshold": orders_below,
        "pct_orders_below": pct_below,
        "expected_aov_increase": f"+{round((optimal_threshold - current_aov) / max(current_aov, 0.01) * 100)}% if {pct_below}% of customers add items to qualify",
        "key_insight": "Free shipping threshold should be JUST above AOV — customers will add items to qualify. "
                      f"At ${optimal_threshold}, ~{pct_below}% of current orders would need to add more items.",
    }
