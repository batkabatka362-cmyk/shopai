"""Fulfillment model recommendation — self-fulfillment vs 3PL breakeven."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("intelligence.supply.fulfillment_model")


def recommend_fulfillment_model(orders: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Recommend self-fulfillment vs 3PL based on volume.

    Breakeven typically at 100+ orders/day.
    """
    daily_orders = len(orders) / 30 if orders else 0

    self_ship_cost = {
        "per_order": 4.50,  # Labor + materials
        "fixed_monthly": 500,  # Rent, utilities for shipping area
    }
    tpl_cost = {
        "per_order": 3.00,  # Pick + pack fee
        "storage_per_unit": 0.50,  # Monthly storage per unit
        "fixed_monthly": 200,  # Account fee
    }

    monthly_orders = daily_orders * 30
    self_total = self_ship_cost["per_order"] * monthly_orders + self_ship_cost["fixed_monthly"]
    tpl_total = tpl_cost["per_order"] * monthly_orders + tpl_cost["fixed_monthly"] + tpl_cost["storage_per_unit"] * monthly_orders * 0.5

    recommendation = "self_fulfillment" if self_total < tpl_total or daily_orders < 5 else "3pl"

    return {
        "daily_order_volume": round(daily_orders, 1),
        "monthly_orders": round(monthly_orders),
        "cost_comparison": {
            "self_fulfillment": round(self_total, 2),
            "3pl": round(tpl_total, 2),
            "savings": round(abs(self_total - tpl_total), 2),
        },
        "recommendation": recommendation,
        "breakeven_point": "~100 orders/day is typical 3PL breakeven",
        "key_insight": (
            "At your volume, self-fulfillment is more cost-effective. "
            "Consider 3PL when you consistently exceed 100 orders/day."
            if recommendation == "self_fulfillment" else
            "At your volume, 3PL would save money and free up your time for growth."
        ),
    }
