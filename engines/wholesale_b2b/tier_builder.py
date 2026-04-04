"""Wholesale B2B Engine — tier builder.

Builds wholesale pricing tiers based on volume thresholds.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any

_DEFAULT_TIERS = [
    {"tier_name": "starter", "min_qty": 10, "max_qty": 49, "discount_pct": 5.0},
    {"tier_name": "growth", "min_qty": 50, "max_qty": 199, "discount_pct": 12.0},
    {"tier_name": "professional", "min_qty": 200, "max_qty": 499, "discount_pct": 20.0},
    {"tier_name": "enterprise", "min_qty": 500, "max_qty": 999999, "discount_pct": 30.0},
]


def build_tiers(
    products: list[dict[str, Any]],
    pricing_config: dict[str, Any],
) -> dict[str, Any]:
    """Build wholesale pricing tiers.

    Args:
        products: Product list with price field.
        pricing_config: Configuration overrides for tiers.

    Returns:
        Structured dict with pricing tiers.
    """
    try:
        config = copy.deepcopy(pricing_config)
        custom_tiers = config.get("tiers", _DEFAULT_TIERS)

        avg_price = 0.0
        prices = [float(p.get("price", 0.0)) for p in products if p.get("price")]
        if prices:
            avg_price = sum(prices) / len(prices)

        tiers: list[dict[str, Any]] = []
        for tier in custom_tiers:
            discount = float(tier.get("discount_pct", tier.get("discount", 0)))
            unit_price = round(avg_price * (1.0 - discount / 100.0), 2)
            tiers.append({
                "tier_name": tier.get("tier_name", tier.get("name", "custom")),
                "min_quantity": int(tier.get("min_qty", tier.get("min_quantity", 1))),
                "max_quantity": int(tier.get("max_qty", tier.get("max_quantity", 999999))),
                "discount_pct": discount,
                "unit_price": unit_price,
            })

        return {"status": "success", "tiers": tiers}
    except Exception as exc:
        return {"status": "error", "tiers": [], "error": f"Tier building failed: {exc}"}
