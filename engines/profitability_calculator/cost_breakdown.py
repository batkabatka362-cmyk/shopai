"""Profitability Calculator Engine — cost breakdown.

Breaks down all cost components per product: COGS, shipping,
marketing, platform fees, and overhead allocation.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def break_down_costs(
    products: list[dict[str, Any]],
    costs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Break down costs for each product.

    Args:
        products: List of product dicts.
        costs: List of cost record dicts.

    Returns:
        Structured dict with per-product cost breakdowns.
    """
    try:
        cost_map: dict[str, dict[str, Any]] = {}
        for c in costs:
            pid = str(c.get("product_id", ""))
            if pid:
                cost_map[pid] = c

        breakdowns: list[dict[str, Any]] = []

        for item in products:
            pid = str(item.get("id", "unknown"))
            cost = cost_map.get(pid, {})

            cogs = float(cost.get("cogs", 0.0))
            shipping = float(cost.get("shipping_cost", 0.0))
            marketing = float(cost.get("marketing_cost", 0.0))
            platform_fee = float(cost.get("platform_fee", 0.0))
            overhead = float(cost.get("overhead_allocation", 0.0))

            total_cost_per_unit = round(
                cogs + shipping + marketing + platform_fee + overhead, 2,
            )

            breakdowns.append({
                "product_id": pid,
                "cogs": round(cogs, 2),
                "shipping": round(shipping, 2),
                "marketing": round(marketing, 2),
                "platform_fee": round(platform_fee, 2),
                "overhead": round(overhead, 2),
                "total_cost_per_unit": total_cost_per_unit,
            })

        return {"status": "success", "breakdowns": breakdowns}
    except Exception as exc:
        return {"status": "error", "breakdowns": [], "error": f"Cost breakdown failed: {exc}"}
