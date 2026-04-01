"""Surprise and delight planning for customer retention."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_int

logger = get_logger("intelligence.customer.surprise_delight")

# Surprise & delight triggers
SURPRISE_DELIGHT_TRIGGERS = [
    {"trigger": "3rd_order", "action": "handwritten_note", "cost": 2.0, "retention_lift": 0.15},
    {"trigger": "birthday", "action": "birthday_discount_20pct", "cost": "discount", "retention_lift": 0.10},
    {"trigger": "1_year_anniversary", "action": "anniversary_gift", "cost": 5.0, "retention_lift": 0.20},
    {"trigger": "high_value_order", "action": "free_sample_insert", "cost": 3.0, "retention_lift": 0.12},
    {"trigger": "5th_order", "action": "vip_status_upgrade", "cost": 0, "retention_lift": 0.25},
]


def plan_surprise_delight(
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Plan surprise & delight moments to increase retention 15-25%."""
    eligible: dict[str, int] = {}

    for customer in customers:
        if not isinstance(customer, dict):
            continue
        order_count = safe_int(customer.get("orders_count", 0))

        for trigger in SURPRISE_DELIGHT_TRIGGERS:
            t = trigger["trigger"]
            if t == "3rd_order" and order_count == 3:
                eligible[t] = eligible.get(t, 0) + 1
            elif t == "5th_order" and order_count == 5:
                eligible[t] = eligible.get(t, 0) + 1
            elif t == "high_value_order" and order_count >= 1:
                eligible[t] = eligible.get(t, 0) + 1

    return {
        "triggers": SURPRISE_DELIGHT_TRIGGERS,
        "eligible_customers": eligible,
        "estimated_retention_lift": "15-25% for customers who receive surprise moments",
        "key_insight": "The cost of a $3 insert card is trivial compared to the $50+ CAC of acquiring a new customer",
    }
