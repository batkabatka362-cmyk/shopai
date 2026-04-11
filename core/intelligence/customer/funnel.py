"""Customer journey funnel mapping."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_int

logger = get_logger("intelligence.customer.funnel")


def map_customer_journeys(
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Map the typical customer journey and identify drop-off points."""
    total = len(customers)
    if not total:
        return {"status": "no_data"}

    order_counts = [safe_int(c.get("orders_count", 0)) for c in customers if isinstance(c, dict)]
    at_least_1 = sum(1 for oc in order_counts if oc >= 1)
    at_least_2 = sum(1 for oc in order_counts if oc >= 2)
    at_least_3 = sum(1 for oc in order_counts if oc >= 3)
    at_least_5 = sum(1 for oc in order_counts if oc >= 5)

    funnel = [
        {"stage": "Visitors → First Purchase", "rate": round(at_least_1 / max(total, 1) * 100, 1), "count": at_least_1},
        {"stage": "First → Second Purchase", "rate": round(at_least_2 / max(at_least_1, 1) * 100, 1), "count": at_least_2},
        {"stage": "Second → Third Purchase", "rate": round(at_least_3 / max(at_least_2, 1) * 100, 1), "count": at_least_3},
        {"stage": "Third → Loyal (5+)", "rate": round(at_least_5 / max(at_least_3, 1) * 100, 1), "count": at_least_5},
    ]

    # Find biggest drop-off
    biggest_drop = min(funnel, key=lambda f: f["rate"])

    return {
        "funnel": funnel,
        "biggest_dropoff": biggest_drop["stage"],
        "dropoff_rate": biggest_drop["rate"],
        "recommendation": f"Focus on improving '{biggest_drop['stage']}' — currently only {biggest_drop['rate']}% conversion",
    }
