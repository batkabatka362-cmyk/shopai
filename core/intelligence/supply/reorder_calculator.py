"""Reorder point analysis — safety stock, EOQ, and lead time variance."""
from __future__ import annotations

import math
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.supply.reorder_calculator")


def analyze_reorder_points(
    products: list[dict[str, Any]],
    orders: list[dict[str, Any]] | None = None,
    lead_time_days: int = 14,
    lead_time_variance: int = 7,
) -> dict[str, Any]:
    """Calculate reorder points with lead time variance buffer.

    Reorder Point = (avg_daily_sales * max_lead_time) + safety_stock
    Safety Stock = Z * σ * √(lead_time)
    where Z=1.65 for 95% service level, σ = demand std dev
    """
    if not products:
        return {"status": "no_data"}

    # Calculate daily sales per product from orders
    daily_sales: dict[str, float] = {}
    if orders:
        product_units: dict[str, int] = {}
        for order in orders:
            if not isinstance(order, dict):
                continue
            for item in order.get("line_items", []):
                if isinstance(item, dict):
                    pid = str(item.get("product_id", ""))
                    qty = safe_int(item.get("quantity", 1))
                    product_units[pid] = product_units.get(pid, 0) + qty
        for pid, units in product_units.items():
            daily_sales[pid] = units / 30  # Assume 30-day order window

    max_lead_time = lead_time_days + lead_time_variance
    z_score = 1.65  # 95% service level

    results = []
    urgent_reorders = 0

    for product in products:
        if not isinstance(product, dict):
            continue

        pid = str(product.get("id", ""))
        name = product.get("title", product.get("name", f"Product {pid}"))
        current_stock = safe_int(product.get("inventory_quantity", 0))
        avg_daily = daily_sales.get(pid, 0.5)  # Default 0.5/day if no data

        # Safety stock calculation
        demand_std = avg_daily * 0.3  # Assume 30% demand variability
        safety_stock = round(z_score * demand_std * math.sqrt(lead_time_days))

        # Reorder point
        reorder_point = round(avg_daily * max_lead_time + safety_stock)

        # Days until stockout
        days_remaining = round(current_stock / max(avg_daily, 0.01))

        needs_reorder = current_stock <= reorder_point
        is_urgent = days_remaining <= lead_time_days

        if is_urgent:
            urgent_reorders += 1

        # Economic order quantity (simplified)
        annual_demand = avg_daily * 365
        ordering_cost = 25  # $25 per order (admin, shipping setup)
        holding_cost_pct = 0.25  # 25% of item cost per year
        item_cost = safe_float(product.get("cost", 10))
        holding_cost = item_cost * holding_cost_pct
        eoq = round(math.sqrt(2 * annual_demand * ordering_cost / max(holding_cost, 0.01))) if annual_demand > 0 else 0

        results.append({
            "product": name,
            "product_id": pid,
            "current_stock": current_stock,
            "avg_daily_sales": round(avg_daily, 2),
            "reorder_point": reorder_point,
            "safety_stock": safety_stock,
            "days_remaining": days_remaining,
            "needs_reorder": needs_reorder,
            "is_urgent": is_urgent,
            "recommended_order_qty": max(eoq, reorder_point * 2),
            "lead_time": f"{lead_time_days}±{lead_time_variance} days",
        })

    results.sort(key=lambda r: r["days_remaining"])

    return {
        "products_analyzed": len(results),
        "urgent_reorders": urgent_reorders,
        "needs_reorder": sum(1 for r in results if r["needs_reorder"]),
        "details": results,
        "lead_time_config": {
            "expected_days": lead_time_days,
            "variance_days": lead_time_variance,
            "max_lead_time": max_lead_time,
            "service_level": "95%",
        },
    }
