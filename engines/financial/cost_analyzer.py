"""Financial Engine — cost analyzer.

Analyzes cost structure: COGS, operating expenses,
cost per order, and cost breakdown by category.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_costs(
    orders: list[dict[str, Any]],
    products: list[dict[str, Any]],
    costs: dict[str, Any],
) -> dict[str, Any]:
    """Analyze cost structure from orders and cost data.

    Args:
        orders: List of order records.
        products: List of product records with cost info.
        costs: Additional cost data (operating, fixed, etc.).

    Returns:
        Structured dict with cost breakdown.
    """
    try:
        prod_data = copy.deepcopy(products)
        cost_data = copy.deepcopy(costs)

        # Calculate COGS from products sold
        product_costs: dict[str, float] = {}
        for prod in prod_data:
            pid = str(prod.get("id", ""))
            unit_cost = float(prod.get("cost", prod.get("unit_cost", 0)))
            product_costs[pid] = unit_cost

        total_cogs = 0.0
        for order in orders:
            items = order.get("line_items", order.get("items", []))
            if not isinstance(items, list):
                items = []
            for item in items:
                pid = str(item.get("product_id", ""))
                qty = int(item.get("quantity", 1))
                unit_cost = product_costs.get(pid, float(item.get("cost", 0)))
                total_cogs += unit_cost * qty

        total_operating = float(cost_data.get("operating_expenses", 0))
        total_fixed = float(cost_data.get("fixed_costs", 0))
        total_costs = total_cogs + total_operating + total_fixed

        order_count = len(orders)
        cost_per_order = round(total_costs / order_count, 2) if order_count > 0 else 0.0

        return {
            "status": "success",
            "costs": {
                "total_cogs": round(total_cogs, 2),
                "total_operating": round(total_operating, 2),
                "total_costs": round(total_costs, 2),
                "cost_per_order": cost_per_order,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "costs": {},
            "error": f"Cost analysis failed: {exc}",
        }
