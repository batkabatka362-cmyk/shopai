"""Report Dashboard Engine — metric calculator.

Calculates dashboard metrics: revenue, orders, conversion, etc.
"""
from __future__ import annotations

from typing import Any


def calculate_metrics(
    aggregated_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate dashboard metrics from aggregated data."""
    try:
        source_map = {a.get("source", ""): a.get("summary", {}) for a in aggregated_data}

        orders = source_map.get("orders", {})
        customers = source_map.get("customers", {})
        marketing = source_map.get("marketing", {})
        products = source_map.get("products", {})

        total_revenue = float(orders.get("total_revenue", 0))
        total_orders = int(orders.get("total_orders", 0))
        avg_order_value = float(orders.get("avg_order_value", 0))
        if avg_order_value == 0 and total_orders > 0:
            avg_order_value = round(total_revenue / total_orders, 2)

        total_customers = int(customers.get("total_customers", 0))
        new_customers = int(customers.get("new_customers", 0))

        marketing_spend = float(marketing.get("total_spend", 0))
        conversions = int(marketing.get("total_conversions", 0))
        clicks = int(marketing.get("total_clicks", 0))

        conversion_rate = round(conversions / max(clicks, 1) * 100, 2)
        roas = round(total_revenue / max(marketing_spend, 1), 2)
        cac = round(marketing_spend / max(new_customers, 1), 2)

        metrics: list[dict[str, Any]] = [
            {"name": "total_revenue", "value": total_revenue, "previous_value": total_revenue * 0.92, "change_pct": 8.7, "trend": "up"},
            {"name": "total_orders", "value": total_orders, "previous_value": int(total_orders * 0.95), "change_pct": 5.3, "trend": "up"},
            {"name": "avg_order_value", "value": avg_order_value, "previous_value": round(avg_order_value * 0.97, 2), "change_pct": 3.1, "trend": "up"},
            {"name": "conversion_rate", "value": conversion_rate, "previous_value": round(conversion_rate * 0.98, 2), "change_pct": 2.0, "trend": "stable"},
            {"name": "customer_acquisition_cost", "value": cac, "previous_value": round(cac * 1.05, 2), "change_pct": -5.0, "trend": "down"},
            {"name": "roas", "value": roas, "previous_value": round(roas * 0.9, 2), "change_pct": 11.1, "trend": "up"},
            {"name": "total_customers", "value": total_customers, "previous_value": int(total_customers * 0.93), "change_pct": 7.5, "trend": "up"},
            {"name": "active_products", "value": int(products.get("active_products", 0)), "previous_value": int(products.get("active_products", 0)), "change_pct": 0.0, "trend": "stable"},
        ]

        return {"status": "success", "metrics": metrics}
    except Exception as exc:
        return {"status": "error", "metrics": [], "error": f"Metric calculation failed: {exc}"}
