"""Customer Segmentation Engine — data normalizer.

Normalizes customer data: fills missing values, standardizes formats,
computes derived fields like tenure_days. No business logic — just
clean data preparation.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any


def normalize_customers(
    customers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize a list of raw customer records.

    Fills missing values with sensible defaults, enforces types,
    and computes derived fields (tenure_days).

    Args:
        customers: Raw customer dicts from the input payload.

    Returns:
        Structured dict with list of normalized customer records.
    """
    try:
        if not customers:
            return {
                "status": "error",
                "customers": [],
                "error": "No customer data provided",
            }

        normalized: list[dict[str, Any]] = []
        today = datetime.utcnow()

        for raw in customers:
            if not isinstance(raw, dict):
                continue
            customer = _normalize_one(raw, today)
            if customer:
                normalized.append(customer)

        if not normalized:
            return {
                "status": "error",
                "customers": [],
                "error": "No valid customer records after normalization",
            }

        return {
            "status": "success",
            "customers": normalized,
            "count": len(normalized),
        }
    except Exception as exc:
        return {
            "status": "error",
            "customers": [],
            "error": f"Normalization failed: {exc}",
        }


def _normalize_one(
    raw: dict[str, Any],
    today: datetime,
) -> dict[str, Any] | None:
    """Normalize a single customer record."""
    cid = str(raw.get("id", "")).strip()
    if not cid:
        return None

    total_orders = max(int(raw.get("total_orders", 0)), 0)
    total_spent = max(float(raw.get("total_spent", 0.0)), 0.0)
    days_since_last = max(int(raw.get("days_since_last", 0)), 0)
    email_opens = max(int(raw.get("email_opens", 0)), 0)
    cart_abandons = max(int(raw.get("cart_abandons", 0)), 0)

    # Compute avg_order_value from total if missing
    aov = float(raw.get("avg_order_value", 0.0))
    if aov <= 0.0 and total_orders > 0:
        aov = total_spent / total_orders

    # Parse dates for tenure
    first_purchase = str(raw.get("first_purchase", ""))
    last_purchase = str(raw.get("last_purchase", ""))
    tenure_days = _compute_tenure(first_purchase, today)

    # Categories — ensure list
    categories = raw.get("categories_bought", [])
    if isinstance(categories, str):
        categories = [c.strip() for c in categories.split(",") if c.strip()]
    elif not isinstance(categories, list):
        categories = []

    return {
        "id": cid,
        "first_purchase": first_purchase,
        "last_purchase": last_purchase,
        "total_orders": total_orders,
        "total_spent": round(total_spent, 2),
        "avg_order_value": round(aov, 2),
        "days_since_last": days_since_last,
        "categories_bought": categories,
        "email_opens": email_opens,
        "cart_abandons": cart_abandons,
        "tenure_days": tenure_days,
    }


def _compute_tenure(first_purchase: str, today: datetime) -> int:
    """Compute tenure in days from first_purchase date string."""
    if not first_purchase:
        return 0
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(first_purchase, fmt)
            return max((today - dt).days, 0)
        except ValueError:
            continue
    return 0
