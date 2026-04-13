"""Wishlist Engine — social proof builder.

Builds social proof from wishlist data: popularity badges,
trending indicators, and "X people want this" counts.
"""
from __future__ import annotations

import copy
from typing import Any


def build_social_proof(
    analysis: dict[str, Any],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build social proof data from wishlist analysis.

    Args:
        analysis: Wishlist analysis results.
        products: Product records.

    Returns:
        Structured dict with social proof elements.
    """
    try:
        top_wishlisted = analysis.get("top_wishlisted", [])
        total_wishlists = int(analysis.get("total_wishlists", 0))

        badges: list[dict[str, Any]] = []
        trending: list[dict[str, Any]] = []

        for prod in top_wishlisted:
            pid = prod.get("product_id", "")
            wl_count = int(prod.get("wishlist_count", 0))
            title = prod.get("title", "")

            # Popular badge (wishlisted by >5% of users)
            if total_wishlists > 0 and wl_count / total_wishlists > 0.05:
                badges.append({
                    "product_id": pid,
                    "badge": "popular",
                    "text": f"{wl_count} people want this",
                    "intensity": "high" if wl_count > total_wishlists * 0.1 else "medium",
                })

            # Trending (high wishlist count)
            if wl_count >= 5:
                trending.append({
                    "product_id": pid,
                    "title": title,
                    "wishlist_count": wl_count,
                    "display_text": f"Trending — {wl_count} wishlists",
                })

        return {
            "status": "success",
            "social_proof": {
                "badges": badges,
                "trending_products": trending,
                "total_badges": len(badges),
                "total_trending": len(trending),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "social_proof": {},
            "error": f"Social proof building failed: {exc}",
        }
