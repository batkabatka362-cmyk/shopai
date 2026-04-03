"""Financial Engine — revenue calculator.

Calculates revenue metrics from orders: total revenue,
average order value, revenue per product, and growth rates.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_revenue(
    orders: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate revenue metrics from orders.

    Args:
        orders: List of order records.
        products: List of product records.

    Returns:
        Structured dict with revenue breakdown.
    """
    try:
        order_data = copy.deepcopy(orders)

        total_revenue = 0.0
        revenue_by_product: dict[str, float] = {}

        for order in order_data:
            order_total = float(order.get("total", order.get("amount", 0)))
            total_revenue += order_total

            # Track per-product revenue
            items = order.get("line_items", order.get("items", []))
            for item in items:
                pid = str(item.get("product_id", "unknown"))
                item_rev = float(item.get("total", item.get("price", 0)))
                revenue_by_product[pid] = revenue_by_product.get(pid, 0) + item_rev

        order_count = len(order_data)
        avg_order_value = round(total_revenue / order_count, 2) if order_count > 0 else 0.0

        return {
            "status": "success",
            "revenue": {
                "total_revenue": round(total_revenue, 2),
                "order_count": order_count,
                "avg_order_value": avg_order_value,
                "revenue_per_product": {
                    k: round(v, 2)
                    for k, v in sorted(revenue_by_product.items(), key=lambda x: x[1], reverse=True)
                },
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "revenue": {},
            "error": f"Revenue calculation failed: {exc}",
        }
