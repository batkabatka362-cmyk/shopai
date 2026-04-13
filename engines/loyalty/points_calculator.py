"""Loyalty Engine — points calculator.

Calculates points earned and redeemed for each customer based on
their order history and the program's earning rate.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_points(
    customers: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    earning_rate: float,
    current_points: dict[str, int],
) -> dict[str, Any]:
    """Calculate points earned, redeemed, and balance for each customer.

    Args:
        customers: List of CustomerRecord dicts.
        orders: List of OrderRecord dicts.
        earning_rate: Points earned per dollar spent.
        current_points: Dict mapping customer_id to current point balance.

    Returns:
        Structured dict with per-customer points calculations.
    """
    try:
        cust_items = copy.deepcopy(customers)
        order_items = copy.deepcopy(orders)

        # Build order totals per customer
        order_totals: dict[str, float] = {}
        order_counts: dict[str, int] = {}
        for order in order_items:
            cid = str(order.get("customer_id", ""))
            total = float(order.get("total", 0.0))
            order_totals[cid] = order_totals.get(cid, 0.0) + total
            order_counts[cid] = order_counts.get(cid, 0) + 1

        calculations: list[dict[str, Any]] = []

        for customer in cust_items:
            cid = str(customer.get("customer_id", "unknown"))
            total_spent = float(customer.get("total_spent", 0.0))

            # Points from orders in this batch
            batch_spent = order_totals.get(cid, 0.0)
            points_earned = int(batch_spent * earning_rate)

            # Lifetime points based on total_spent
            lifetime_points = int(total_spent * earning_rate)

            # Current balance from input (or compute from lifetime)
            existing_balance = current_points.get(cid, lifetime_points)

            # Points redeemed = lifetime earned - current balance (if balance < lifetime)
            points_redeemed = max(0, lifetime_points - existing_balance)

            # New balance = existing + newly earned
            points_balance = existing_balance + points_earned

            calculations.append({
                "customer_id": cid,
                "points_earned": points_earned,
                "points_redeemed": points_redeemed,
                "points_balance": points_balance,
                "lifetime_points": lifetime_points + points_earned,
            })

        return {
            "status": "success",
            "calculations": calculations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "calculations": [],
            "error": f"Points calculation failed: {exc}",
        }
