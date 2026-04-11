"""Upsell Engine — product analyzer.

Analyzes the current product to understand its position: tier level,
feature set richness, price point classification, margin headroom,
and whether there is room to upsell.

All classification is deterministic — no randomness.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Tier hierarchy — canonical ordering
# ---------------------------------------------------------------------------

TIER_RANKS: dict[str, int] = {
    "free": 1,
    "basic": 2,
    "starter": 2,
    "standard": 3,
    "plus": 3,
    "premium": 4,
    "pro": 4,
    "enterprise": 5,
    "ultimate": 5,
}

MAX_TIER_RANK = 5

# ---------------------------------------------------------------------------
# Price position thresholds (category-agnostic defaults)
# ---------------------------------------------------------------------------

_PRICE_POSITIONS: list[tuple[float, str]] = [
    (25.0, "budget"),
    (75.0, "mid_range"),
    (200.0, "premium"),
    (float("inf"), "luxury"),
]

# ---------------------------------------------------------------------------
# Category-specific margin expectations
# ---------------------------------------------------------------------------

_CATEGORY_MARGINS: dict[str, float] = {
    "electronics": 0.15,
    "software": 0.70,
    "clothing": 0.50,
    "food": 0.30,
    "beauty": 0.60,
    "home": 0.40,
    "sports": 0.35,
}

_DEFAULT_MARGIN = 0.40


def analyze_product(
    current_product: dict[str, Any],
) -> dict[str, Any]:
    """Analyze the current product for upsell positioning.

    Args:
        current_product: CurrentProduct dict with id, title, category,
            price, tier, features.

    Returns:
        Structured dict with ProductAnalysis data and status.
    """
    try:
        product = copy.deepcopy(current_product)
        if not isinstance(product, dict):
            return {
                "status": "error",
                "analysis": {},
                "error": "current_product must be a dict",
            }

        product_id = str(product.get("id", "unknown"))
        title = str(product.get("title", ""))
        category = str(product.get("category", "general")).lower().strip()
        price = float(product.get("price", 0.0))
        tier = str(product.get("tier", "standard")).lower().strip()
        features = product.get("features", [])
        if not isinstance(features, list):
            features = []

        # --- Tier ranking ---
        tier_rank = TIER_RANKS.get(tier, 3)

        # --- Price position ---
        price_position = _classify_price_position(price)

        # --- Feature count ---
        feature_count = len(features)

        # --- Upgrade room ---
        has_upgrade_room = tier_rank < MAX_TIER_RANK

        # --- Margin headroom estimate ---
        category_margin = _CATEGORY_MARGINS.get(category, _DEFAULT_MARGIN)
        # Higher-tier products tend to have better margins
        tier_margin_bonus = (tier_rank - 1) * 0.03
        margin_headroom = min(category_margin + tier_margin_bonus, 0.85)

        return {
            "status": "success",
            "analysis": {
                "product_id": product_id,
                "title": title,
                "category": category,
                "price": round(price, 2),
                "tier": tier,
                "tier_rank": tier_rank,
                "feature_count": feature_count,
                "price_position": price_position,
                "has_upgrade_room": has_upgrade_room,
                "margin_headroom": round(margin_headroom, 4),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "analysis": {},
            "error": f"Product analysis failed: {exc}",
        }


def _classify_price_position(price: float) -> str:
    """Classify price into a market position bucket."""
    for threshold, label in _PRICE_POSITIONS:
        if price < threshold:
            return label
    return "luxury"
