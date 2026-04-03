"""Wishlist Engine — price alert manager.

Manages price drop alerts: identifies products with recent
price changes, matches to wishlists, and queues notifications.
"""
from __future__ import annotations

import copy
from typing import Any


def manage_price_alerts(
    wishlists: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Manage price drop alerts for wishlisted products.

    Args:
        wishlists: Wishlist records.
        products: Product records with price history.

    Returns:
        Structured dict with price alert data.
    """
    try:
        wl_data = copy.deepcopy(wishlists)
        prods = copy.deepcopy(products)

        # Build product price lookup
        prod_map: dict[str, dict[str, Any]] = {}
        for prod in prods:
            pid = str(prod.get("id", ""))
            prod_map[pid] = prod

        alerts: list[dict[str, Any]] = []

        # Find products with price drops
        for prod in prods:
            pid = str(prod.get("id", ""))
            current_price = float(prod.get("price", 0))
            prev_price = float(prod.get("previous_price", prod.get("compare_at_price", 0)))

            if prev_price > 0 and current_price < prev_price:
                discount_pct = round((1 - current_price / prev_price) * 100, 1)

                # Find users who wishlisted this product
                affected_users: list[str] = []
                for wl in wl_data:
                    items = wl.get("items", wl.get("product_ids", []))
                    item_ids = [
                        str(i.get("product_id", i) if isinstance(i, dict) else i)
                        for i in items
                    ]
                    if pid in item_ids:
                        user_id = str(wl.get("user_id", wl.get("customer_id", "")))
                        if user_id:
                            affected_users.append(user_id)

                if affected_users:
                    alerts.append({
                        "product_id": pid,
                        "title": str(prod.get("title", "")),
                        "current_price": current_price,
                        "previous_price": prev_price,
                        "discount_pct": discount_pct,
                        "affected_users": affected_users,
                        "user_count": len(affected_users),
                    })

        alerts.sort(key=lambda a: a["user_count"], reverse=True)

        return {
            "status": "success",
            "price_alerts": alerts,
            "total_alerts": len(alerts),
            "total_users_to_notify": sum(a["user_count"] for a in alerts),
        }
    except Exception as exc:
        return {
            "status": "error",
            "price_alerts": [],
            "error": f"Price alert management failed: {exc}",
        }
