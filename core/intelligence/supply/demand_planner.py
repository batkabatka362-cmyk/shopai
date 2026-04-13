"""Demand planning — velocity tracking and promotional lift guide."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_int

logger = get_logger("intelligence.supply.demand_planner")


def plan_demand(
    products: list[dict[str, Any]],
    orders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Demand planning with promotional lift and cannibalization awareness."""
    if not products:
        return {"status": "no_data"}

    # Calculate velocity per product
    product_velocity: dict[str, float] = {}
    if orders:
        for order in orders:
            if not isinstance(order, dict):
                continue
            for item in order.get("line_items", []):
                if isinstance(item, dict):
                    pid = str(item.get("product_id", ""))
                    qty = safe_int(item.get("quantity", 1))
                    product_velocity[pid] = product_velocity.get(pid, 0) + qty

    fast_movers = []
    slow_movers = []
    for product in products:
        if not isinstance(product, dict):
            continue
        pid = str(product.get("id", ""))
        name = product.get("title", product.get("name", f"Product {pid}"))
        units = product_velocity.get(pid, 0)
        daily_velocity = units / 30

        entry = {"product": name, "units_30d": units, "daily_velocity": round(daily_velocity, 2)}
        if daily_velocity >= 1:
            fast_movers.append(entry)
        else:
            slow_movers.append(entry)

    fast_movers.sort(key=lambda x: x["daily_velocity"], reverse=True)
    slow_movers.sort(key=lambda x: x["daily_velocity"])

    return {
        "fast_movers": fast_movers[:10],
        "slow_movers": slow_movers[:10],
        "promotional_lift_guide": {
            "10%_discount": "Expected 1.5x volume lift",
            "20%_discount": "Expected 2.5x volume lift",
            "30%_discount": "Expected 3.5x volume lift",
            "bogo": "Expected 4x volume lift but 50% margin hit",
            "free_shipping": "Expected 1.3x volume lift",
        },
        "cannibalization_warning": (
            "Launching similar products may cannibalize existing sales. "
            "Track net revenue change, not just new product revenue."
        ),
    }
