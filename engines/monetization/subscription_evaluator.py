"""Monetization Engine — subscription evaluator.

Evaluates subscription/recurring revenue potential based on
product types, purchase frequency, and customer retention.
"""
from __future__ import annotations

import copy
from typing import Any


def evaluate_subscriptions(
    products: list[dict[str, Any]],
    customers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate subscription revenue potential.

    Args:
        products: Product catalog.
        customers: Customer records with purchase history.

    Returns:
        Structured dict with subscription evaluation.
    """
    try:
        prods = copy.deepcopy(products)
        custs = copy.deepcopy(customers)

        # Identify repeat-purchase products (consumables, refills)
        subscription_candidates: list[dict[str, Any]] = []

        for prod in prods:
            is_consumable = prod.get("is_consumable", False)
            avg_reorder_days = float(prod.get("avg_reorder_days", 0))
            repeat_rate = float(prod.get("repeat_purchase_rate", 0))

            if is_consumable or repeat_rate > 0.3 or (avg_reorder_days > 0 and avg_reorder_days < 90):
                price = float(prod.get("price", 0))
                subscription_candidates.append({
                    "product_id": str(prod.get("id", "")),
                    "title": str(prod.get("title", "")),
                    "price": price,
                    "repeat_rate": repeat_rate,
                    "suggested_interval_days": int(avg_reorder_days) if avg_reorder_days > 0 else 30,
                    "monthly_revenue_potential": round(price * repeat_rate * 0.9, 2),
                })

        # Customer loyalty metrics
        repeat_customers = sum(1 for c in custs if int(c.get("order_count", 0)) > 1)
        repeat_rate = round(repeat_customers / len(custs) * 100, 1) if custs else 0.0

        viable = len(subscription_candidates) > 0 and repeat_rate > 20

        return {
            "status": "success",
            "candidates": subscription_candidates,
            "repeat_customer_rate": repeat_rate,
            "subscription_viable": viable,
            "total_candidates": len(subscription_candidates),
        }
    except Exception as exc:
        return {
            "status": "error",
            "candidates": [],
            "error": f"Subscription evaluation failed: {exc}",
        }
