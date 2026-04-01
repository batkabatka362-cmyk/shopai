"""Marketplace trends data — BSR mapping, categories, fee structures."""
from __future__ import annotations
from typing import Any

# Amazon BSR → estimated daily sales (US, approximate)
BSR_VOLUME_MAP = {
    1: 3000, 10: 1500, 50: 800, 100: 500, 500: 150,
    1000: 80, 2000: 40, 5000: 15, 10000: 8, 20000: 4,
    50000: 2, 100000: 1,
}

# Top Amazon categories with approximate product counts
AMAZON_CATEGORIES = {
    "Electronics": {"products": 5000000, "avg_bsr_top100_sales": 300},
    "Home & Kitchen": {"products": 8000000, "avg_bsr_top100_sales": 200},
    "Clothing": {"products": 12000000, "avg_bsr_top100_sales": 150},
    "Health & Household": {"products": 4000000, "avg_bsr_top100_sales": 250},
    "Sports & Outdoors": {"products": 3000000, "avg_bsr_top100_sales": 120},
    "Beauty": {"products": 3000000, "avg_bsr_top100_sales": 180},
    "Toys & Games": {"products": 2000000, "avg_bsr_top100_sales": 200},
    "Pet Supplies": {"products": 1500000, "avg_bsr_top100_sales": 130},
    "Baby": {"products": 1000000, "avg_bsr_top100_sales": 110},
    "Patio & Garden": {"products": 2000000, "avg_bsr_top100_sales": 100},
}

# Marketplace fee structures (% of sale price)
MARKETPLACE_FEES = {
    "amazon_fba": {"referral_pct": 0.15, "fba_per_unit": 3.50, "storage_monthly": 0.75, "total_estimate": 0.30},
    "amazon_fbm": {"referral_pct": 0.15, "shipping_avg": 5.00, "total_estimate": 0.20},
    "shopify": {"transaction_pct": 0.029, "subscription": 39, "total_estimate": 0.05},
    "etsy": {"listing_fee": 0.20, "transaction_pct": 0.065, "payment_pct": 0.03, "total_estimate": 0.12},
    "walmart": {"referral_pct": 0.12, "total_estimate": 0.15},
}

def get_bsr_volume_estimate(bsr_rank: int) -> int:
    """Estimate daily sales from BSR rank (interpolation)."""
    if bsr_rank <= 0:
        return 0
    sorted_ranks = sorted(BSR_VOLUME_MAP.keys())
    for i, rank in enumerate(sorted_ranks):
        if bsr_rank <= rank:
            if i == 0:
                return BSR_VOLUME_MAP[rank]
            prev_rank = sorted_ranks[i - 1]
            prev_vol = BSR_VOLUME_MAP[prev_rank]
            curr_vol = BSR_VOLUME_MAP[rank]
            ratio = (bsr_rank - prev_rank) / (rank - prev_rank)
            return round(prev_vol + (curr_vol - prev_vol) * ratio)
    return 1  # Very low rank

def get_marketplace_fees(platform: str) -> dict[str, Any]:
    return MARKETPLACE_FEES.get(platform, MARKETPLACE_FEES["shopify"])
