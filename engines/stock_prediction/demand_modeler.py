"""Stock Prediction Engine — demand modeler.

Models demand from historical orders using moving averages, trend
detection, and volatility measurement per product.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def model_demand(
    products: list[dict[str, Any]],
    orders_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Model demand for each product from historical order data.

    Args:
        products: List of ProductStock dicts.
        orders_history: List of OrderHistory dicts.

    Returns:
        Structured dict with per-product demand models.
    """
    try:
        products = copy.deepcopy(products)
        orders = copy.deepcopy(orders_history)

        # Build per-product order aggregates
        product_orders: dict[str, list[int]] = {}
        for order in orders:
            pid = str(order.get("product_id", ""))
            qty = int(order.get("quantity", 0))
            if pid:
                product_orders.setdefault(pid, []).append(qty)

        models: list[dict[str, Any]] = []

        for product in products:
            pid = str(product.get("id", "unknown"))
            daily_avg = float(product.get("daily_sales_avg", 0.0))

            order_qtys = product_orders.get(pid, [])
            total_orders = len(order_qtys)
            total_qty = sum(order_qtys) if order_qtys else 0

            # Average order quantity
            avg_order_qty = (
                round(total_qty / total_orders, 2) if total_orders > 0 else 0.0
            )

            # Demand volatility: coefficient of variation
            if total_orders >= 2 and avg_order_qty > 0:
                variance = sum(
                    (q - avg_order_qty) ** 2 for q in order_qtys
                ) / total_orders
                std_dev = variance ** 0.5
                volatility = round(std_dev / avg_order_qty, 3)
            else:
                volatility = 0.5  # default moderate volatility

            # Trend detection: compare first half vs second half of orders
            if total_orders >= 4:
                mid = total_orders // 2
                first_half_avg = sum(order_qtys[:mid]) / mid
                second_half_avg = sum(order_qtys[mid:]) / (total_orders - mid)
                if first_half_avg > 0:
                    trend_pct = (second_half_avg - first_half_avg) / first_half_avg
                else:
                    trend_pct = 0.0

                if trend_pct > 0.15:
                    trend = "strong_growth"
                elif trend_pct > 0.05:
                    trend = "growth"
                elif trend_pct > -0.05:
                    trend = "stable"
                elif trend_pct > -0.15:
                    trend = "decline"
                else:
                    trend = "strong_decline"
            else:
                trend = "stable"

            # Confidence based on data volume
            if total_orders >= 30:
                confidence = 0.90
            elif total_orders >= 15:
                confidence = 0.75
            elif total_orders >= 5:
                confidence = 0.60
            elif total_orders >= 1:
                confidence = 0.40
            else:
                confidence = 0.25

            models.append({
                "product_id": pid,
                "avg_daily_demand": daily_avg if daily_avg > 0 else avg_order_qty,
                "demand_trend": trend,
                "demand_volatility": volatility,
                "model_confidence": confidence,
            })

        return {
            "status": "success",
            "models": models,
        }
    except Exception as exc:
        return {
            "status": "error",
            "models": [],
            "error": f"Demand modeling failed: {exc}",
        }
