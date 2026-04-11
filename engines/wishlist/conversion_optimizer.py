"""Wishlist Engine — conversion optimizer.

Optimizes wishlist-to-purchase conversion: identifies
high-intent users, suggests promotions, and timing.
"""
from __future__ import annotations

import copy
from typing import Any


def optimize_conversion(
    wishlists: list[dict[str, Any]],
    products: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Optimize wishlist to purchase conversion.

    Args:
        wishlists: Wishlist records.
        products: Product records.
        analysis: Wishlist analysis results.

    Returns:
        Structured dict with conversion recommendations.
    """
    try:
        wl_data = copy.deepcopy(wishlists)
        recommendations: list[dict[str, Any]] = []

        # Identify high-intent users (large wishlists, recent activity)
        for wl in wl_data:
            user_id = str(wl.get("user_id", wl.get("customer_id", "")))
            items = wl.get("items", wl.get("product_ids", []))
            item_count = len(items)
            total_value = 0.0

            prod_map = {str(p.get("id", "")): p for p in products}
            for item in items:
                pid = str(item.get("product_id", item) if isinstance(item, dict) else item)
                prod = prod_map.get(pid, {})
                total_value += float(prod.get("price", 0))

            if item_count >= 3:
                recommendations.append({
                    "type": "high_intent_user",
                    "user_id": user_id,
                    "wishlist_size": item_count,
                    "total_value": round(total_value, 2),
                    "action": "Send personalized offer with free shipping",
                })
            elif item_count >= 1 and total_value > 100:
                recommendations.append({
                    "type": "high_value_wishlist",
                    "user_id": user_id,
                    "wishlist_size": item_count,
                    "total_value": round(total_value, 2),
                    "action": "Offer 10% discount on wishlist items",
                })

        # General recommendations based on analysis
        top_wishlisted = analysis.get("top_wishlisted", [])
        for prod in top_wishlisted[:5]:
            if prod.get("wishlist_count", 0) > 10:
                recommendations.append({
                    "type": "popular_product",
                    "product_id": prod.get("product_id", ""),
                    "wishlist_count": prod.get("wishlist_count", 0),
                    "action": f"Create urgency: '{prod.get('title', '')}' is popular — consider limited-time offer",
                })

        return {
            "status": "success",
            "recommendations": recommendations,
            "total_recommendations": len(recommendations),
        }
    except Exception as exc:
        return {
            "status": "error",
            "recommendations": [],
            "error": f"Conversion optimization failed: {exc}",
        }
