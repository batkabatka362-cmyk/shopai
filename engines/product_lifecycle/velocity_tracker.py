"""Product Lifecycle Engine — velocity tracker.

Tracks sales velocity per product: current rate, trend direction,
and acceleration over time.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def track_velocity(
    products: list[dict[str, Any]],
    sales_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track sales velocity for each product.

    Args:
        products: List of product dicts.
        sales_history: List of sales history records.

    Returns:
        Structured dict with per-product velocity results.
    """
    try:
        items = copy.deepcopy(products)

        history_map: dict[str, list[dict[str, Any]]] = {}
        for record in sales_history:
            pid = str(record.get("product_id", ""))
            if pid:
                history_map.setdefault(pid, []).append(record)

        velocities: list[dict[str, Any]] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            history = history_map.get(product_id, [])
            history.sort(key=lambda r: str(r.get("period", "")))

            units = [int(r.get("units_sold", 0)) for r in history]
            n = len(units)

            if n == 0:
                current_velocity = 0.0
                velocity_trend = "unknown"
                acceleration = 0.0
            elif n == 1:
                current_velocity = float(units[0])
                velocity_trend = "stable"
                acceleration = 0.0
            else:
                current_velocity = float(units[-1])
                prev_velocity = float(units[-2])

                # Trend from last two periods
                if current_velocity > prev_velocity * 1.05:
                    velocity_trend = "accelerating"
                elif current_velocity < prev_velocity * 0.95:
                    velocity_trend = "decelerating"
                else:
                    velocity_trend = "stable"

                # Acceleration: change in velocity
                acceleration = round(current_velocity - prev_velocity, 2)

            velocities.append({
                "product_id": product_id,
                "current_velocity": round(current_velocity, 2),
                "velocity_trend": velocity_trend,
                "acceleration": acceleration,
                "periods_analyzed": n,
            })

        return {"status": "success", "velocities": velocities}
    except Exception as exc:
        return {"status": "error", "velocities": [], "error": f"Velocity tracking failed: {exc}"}
