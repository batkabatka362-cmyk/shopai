"""Marketplace trends data — BSR volume mapping, categories, and fee structures.

Amazon BSR-to-sales mapping is the core dataset here:
  - BSR #1 in a major category ~ 3000+ units/day
  - BSR #100 ~ 100-300 units/day depending on category
  - BSR #1000 ~ 10-50 units/day
  - BSR #10000 ~ 1-5 units/day
  - BSR #100000+ ~ a few per week at best

These are approximations — actual volume varies by category size.
"""
from __future__ import annotations

from typing import Any

from utils.helpers import safe_int


# Amazon BSR -> estimated daily sales by broad category size tier
# Tier "large" = Electronics, Home, Clothing; "medium" = Pet, Beauty; "small" = Industrial, Musical
BSR_VOLUME_MAP: dict[str, list[dict[str, Any]]] = {
    "large": [
        {"bsr_max": 1, "daily_sales_min": 2500, "daily_sales_max": 5000},
        {"bsr_max": 10, "daily_sales_min": 800, "daily_sales_max": 2500},
        {"bsr_max": 50, "daily_sales_min": 300, "daily_sales_max": 800},
        {"bsr_max": 100, "daily_sales_min": 150, "daily_sales_max": 350},
        {"bsr_max": 500, "daily_sales_min": 50, "daily_sales_max": 150},
        {"bsr_max": 1000, "daily_sales_min": 20, "daily_sales_max": 60},
        {"bsr_max": 5000, "daily_sales_min": 5, "daily_sales_max": 25},
        {"bsr_max": 10000, "daily_sales_min": 2, "daily_sales_max": 8},
        {"bsr_max": 50000, "daily_sales_min": 1, "daily_sales_max": 3},
        {"bsr_max": 100000, "daily_sales_min": 0, "daily_sales_max": 1},
    ],
    "medium": [
        {"bsr_max": 1, "daily_sales_min": 1000, "daily_sales_max": 2500},
        {"bsr_max": 10, "daily_sales_min": 400, "daily_sales_max": 1000},
        {"bsr_max": 50, "daily_sales_min": 150, "daily_sales_max": 400},
        {"bsr_max": 100, "daily_sales_min": 70, "daily_sales_max": 180},
        {"bsr_max": 500, "daily_sales_min": 25, "daily_sales_max": 80},
        {"bsr_max": 1000, "daily_sales_min": 10, "daily_sales_max": 30},
        {"bsr_max": 5000, "daily_sales_min": 3, "daily_sales_max": 12},
        {"bsr_max": 10000, "daily_sales_min": 1, "daily_sales_max": 4},
        {"bsr_max": 50000, "daily_sales_min": 0, "daily_sales_max": 2},
    ],
    "small": [
        {"bsr_max": 1, "daily_sales_min": 300, "daily_sales_max": 800},
        {"bsr_max": 10, "daily_sales_min": 100, "daily_sales_max": 300},
        {"bsr_max": 50, "daily_sales_min": 40, "daily_sales_max": 120},
        {"bsr_max": 100, "daily_sales_min": 20, "daily_sales_max": 50},
        {"bsr_max": 500, "daily_sales_min": 5, "daily_sales_max": 25},
        {"bsr_max": 1000, "daily_sales_min": 2, "daily_sales_max": 8},
        {"bsr_max": 5000, "daily_sales_min": 1, "daily_sales_max": 3},
        {"bsr_max": 10000, "daily_sales_min": 0, "daily_sales_max": 2},
    ],
}

# Amazon top-level categories mapped to size tier
AMAZON_CATEGORIES: dict[str, dict[str, Any]] = {
    "electronics": {"tier": "large", "avg_referral_fee_pct": 0.08, "avg_fba_fee": 4.75},
    "home_kitchen": {"tier": "large", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 4.25},
    "clothing": {"tier": "large", "avg_referral_fee_pct": 0.17, "avg_fba_fee": 4.00},
    "sports_outdoors": {"tier": "large", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 4.50},
    "health_beauty": {"tier": "medium", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 3.75},
    "pet_supplies": {"tier": "medium", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 3.50},
    "beauty": {"tier": "medium", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 3.50},
    "baby": {"tier": "medium", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 3.75},
    "toys_games": {"tier": "medium", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 3.50},
    "tools_home_improvement": {"tier": "medium", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 5.00},
    "jewelry": {"tier": "small", "avg_referral_fee_pct": 0.20, "avg_fba_fee": 3.25},
    "musical_instruments": {"tier": "small", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 5.50},
    "industrial": {"tier": "small", "avg_referral_fee_pct": 0.12, "avg_fba_fee": 5.00},
    "office_products": {"tier": "small", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 3.50},
    "arts_crafts": {"tier": "small", "avg_referral_fee_pct": 0.15, "avg_fba_fee": 3.50},
}

# Marketplace fee structures for margin estimation
MARKETPLACE_FEES: dict[str, dict[str, Any]] = {
    "amazon_fba": {
        "referral_fee_pct": 0.15,
        "fba_fee_avg": 4.00,
        "monthly_storage_per_unit": 0.75,
        "advertising_pct": 0.10,
        "total_effective_pct": 0.35,
    },
    "amazon_fbm": {
        "referral_fee_pct": 0.15,
        "shipping_avg": 5.00,
        "advertising_pct": 0.10,
        "total_effective_pct": 0.30,
    },
    "shopify": {
        "platform_fee_pct": 0.029,
        "transaction_fee": 0.30,
        "app_fees_monthly": 50,
        "shipping_avg": 5.50,
        "advertising_pct": 0.15,
        "total_effective_pct": 0.25,
    },
    "etsy": {
        "listing_fee": 0.20,
        "transaction_fee_pct": 0.065,
        "payment_processing_pct": 0.03,
        "payment_processing_flat": 0.25,
        "advertising_pct": 0.12,
        "total_effective_pct": 0.22,
    },
}


def get_bsr_volume_estimate(bsr_rank: int, category: str = "") -> dict[str, Any]:
    """Estimate daily sales volume from an Amazon BSR rank.

    Returns min/max daily sales estimate plus the category tier used.
    """
    rank = safe_int(bsr_rank)
    if rank <= 0:
        return {"daily_sales_min": 0, "daily_sales_max": 0, "tier": "unknown", "note": "Invalid BSR"}

    # Determine category tier
    cat_key = category.lower().replace(" ", "_").replace("&", "_")
    cat_info = AMAZON_CATEGORIES.get(cat_key)
    tier = cat_info["tier"] if cat_info else "medium"

    volume_table = BSR_VOLUME_MAP.get(tier, BSR_VOLUME_MAP["medium"])

    for bracket in volume_table:
        if rank <= bracket["bsr_max"]:
            return {
                "daily_sales_min": bracket["daily_sales_min"],
                "daily_sales_max": bracket["daily_sales_max"],
                "tier": tier,
                "bsr_bracket": f"Top {bracket['bsr_max']}",
                "note": f"BSR #{rank} in {tier} category",
            }

    # Beyond the table — very low sales
    return {
        "daily_sales_min": 0,
        "daily_sales_max": 1,
        "tier": tier,
        "bsr_bracket": f">{volume_table[-1]['bsr_max']}",
        "note": f"BSR #{rank} is very deep — minimal sales expected",
    }


def estimate_marketplace_margin(
    price: float, cost: float, marketplace: str = "amazon_fba", category: str = ""
) -> dict[str, Any]:
    """Estimate profit margin after marketplace fees."""
    if price <= 0:
        return {"viable": False, "reason": "Price must be positive", "margin_pct": 0}

    fees = MARKETPLACE_FEES.get(marketplace, MARKETPLACE_FEES["amazon_fba"])
    effective_fee_pct = fees["total_effective_pct"]

    # Category-specific referral fee override for Amazon
    if marketplace.startswith("amazon") and category:
        cat_key = category.lower().replace(" ", "_")
        cat_info = AMAZON_CATEGORIES.get(cat_key)
        if cat_info:
            effective_fee_pct = (
                cat_info["avg_referral_fee_pct"]
                + fees.get("advertising_pct", 0.10)
                + cat_info["avg_fba_fee"] / max(price, 1)
            )

    total_fees = price * effective_fee_pct
    gross_profit = price - cost - total_fees
    margin_pct = round(gross_profit / price, 3) if price > 0 else 0

    return {
        "viable": margin_pct >= 0.30,
        "price": price,
        "cost": cost,
        "estimated_fees": round(total_fees, 2),
        "gross_profit": round(gross_profit, 2),
        "margin_pct": margin_pct,
        "marketplace": marketplace,
        "note": "Target 30%+ margin for sustainable marketplace business",
    }
