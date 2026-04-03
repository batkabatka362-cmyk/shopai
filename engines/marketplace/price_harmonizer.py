"""Marketplace Engine — price harmonizer.

Harmonizes product prices across marketplaces, accounting for
platform fees, competitive positioning, and margin requirements.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Fee structures per marketplace (referral % + fixed per-item fee)
# ---------------------------------------------------------------------------

_FEE_STRUCTURES: dict[str, dict[str, float]] = {
    "amazon": {"referral_pct": 15.0, "fixed": 0.99},
    "etsy": {"referral_pct": 6.5, "fixed": 0.20},
    "ebay": {"referral_pct": 12.9, "fixed": 0.30},
}

_DEFAULT_FEE = {"referral_pct": 10.0, "fixed": 0.0}

# Minimum acceptable margin percentage
_MIN_MARGIN_PCT = 10.0


def harmonize_prices(
    products: list[dict[str, Any]],
    marketplaces: list[str],
    pricing: dict[str, Any],
) -> dict[str, Any]:
    """Harmonize prices across marketplace platforms.

    Args:
        products: List of product dicts (must have 'price', 'id').
        marketplaces: List of marketplace platform names.
        pricing: Global pricing config (may contain min_margin_pct, rounding).

    Returns:
        Structured dict with price adjustments.
    """
    try:
        items = copy.deepcopy(products)
        min_margin = float(pricing.get("min_margin_pct", _MIN_MARGIN_PCT))
        adjustments: list[dict[str, Any]] = []

        for product in items:
            pid = str(product.get("id", "unknown"))
            base_price = float(product.get("price", 0.0))
            unit_cost = float(product.get("unit_cost", base_price * 0.5))

            if base_price <= 0:
                continue

            for platform in marketplaces:
                platform_lower = platform.lower()
                fees = _FEE_STRUCTURES.get(platform_lower, _DEFAULT_FEE)

                referral = base_price * fees["referral_pct"] / 100.0
                total_fee = referral + fees["fixed"]
                net_revenue = base_price - total_fee

                current_margin = (
                    (net_revenue - unit_cost) / base_price * 100.0
                    if base_price > 0 else 0.0
                )

                if current_margin >= min_margin:
                    recommended = base_price
                    reason = "price_acceptable"
                else:
                    # Solve for price: (price - fee(price) - cost) / price >= min_margin
                    # price - price*ref_pct/100 - fixed - cost >= price * min_margin/100
                    # price * (1 - ref_pct/100 - min_margin/100) >= cost + fixed
                    factor = 1.0 - fees["referral_pct"] / 100.0 - min_margin / 100.0
                    if factor > 0:
                        recommended = round((unit_cost + fees["fixed"]) / factor, 2)
                    else:
                        recommended = round(base_price * 1.2, 2)
                    reason = "margin_below_minimum"

                # Apply rounding strategy
                rounding = str(pricing.get("rounding", "99"))
                if rounding == "99":
                    recommended = float(int(recommended)) + 0.99
                elif rounding == "95":
                    recommended = float(int(recommended)) + 0.95

                rec_referral = recommended * fees["referral_pct"] / 100.0
                rec_net = recommended - rec_referral - fees["fixed"]
                margin_impact = (
                    (rec_net - unit_cost) / recommended * 100.0
                    if recommended > 0 else 0.0
                )

                adjustments.append({
                    "product_id": pid,
                    "platform": platform,
                    "current_price": base_price,
                    "recommended_price": round(recommended, 2),
                    "adjustment_reason": reason,
                    "margin_impact_pct": round(margin_impact, 2),
                })

        return {
            "status": "success",
            "adjustments": adjustments,
        }
    except Exception as exc:
        return {
            "status": "error",
            "adjustments": [],
            "error": f"Price harmonization failed: {exc}",
        }
