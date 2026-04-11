"""ROI projection reference data — growth curves, seasonality, and ad benchmarks.

Empirical data from Shopify store analytics, ad platform benchmarks, and
e-commerce industry reports. Used to make projections realistic rather than
just linear extrapolations.
"""
from __future__ import annotations

from typing import Any


# Growth curve benchmarks for new Shopify stores
# Multiplier relative to month-1 baseline sales velocity.
# New stores follow an S-curve: slow start, rapid growth, then plateau.
GROWTH_CURVE_BENCHMARKS = {
    "general": {
        1: 0.40,    # Month 1: 40% of expected — ramp-up, few reviews
        2: 0.65,    # Month 2: gaining traction, some organic
        3: 0.85,    # Month 3: reviews accumulating, SEO indexing
        4: 1.00,    # Month 4: reaching expected velocity
        5: 1.10,
        6: 1.20,    # Month 6: organic traffic building
        7: 1.25,
        8: 1.30,
        9: 1.35,
        10: 1.40,
        11: 1.45,
        12: 1.50,   # Month 12: 50% above initial baseline
    },
    "health_beauty": {
        1: 0.35,    # Slower start — trust building needed
        2: 0.55,
        3: 0.80,
        4: 1.00,
        5: 1.20,    # Reviews kick in — social proof effect
        6: 1.40,
        7: 1.55,
        8: 1.70,    # Repeat purchases start compounding
        9: 1.85,
        10: 2.00,
        11: 2.10,
        12: 2.20,   # Strong LTV — 2.2x month-1 by end of year
    },
    "electronics": {
        1: 0.50,    # Faster start — buyers research less for accessories
        2: 0.75,
        3: 0.90,
        4: 1.00,
        5: 1.05,
        6: 1.10,
        7: 1.12,
        8: 1.15,
        9: 1.18,
        10: 1.20,
        11: 1.22,
        12: 1.25,   # Modest growth — competitive, price-sensitive
    },
    "pet_supplies": {
        1: 0.45,
        2: 0.70,
        3: 0.90,
        4: 1.00,
        5: 1.15,
        6: 1.35,
        7: 1.50,
        8: 1.65,
        9: 1.80,
        10: 1.95,
        11: 2.05,
        12: 2.15,   # Strong repeat purchases — pets eat every day
    },
    "clothing": {
        1: 0.30,    # Very slow start — sizing concerns, return risk
        2: 0.50,
        3: 0.70,
        4: 0.90,
        5: 1.00,
        6: 1.10,
        7: 1.15,
        8: 1.20,
        9: 1.25,
        10: 1.30,
        11: 1.35,
        12: 1.40,   # Moderate growth — high return rates slow momentum
    },
    "food_beverage": {
        1: 0.35,
        2: 0.60,
        3: 0.85,
        4: 1.00,
        5: 1.25,
        6: 1.50,
        7: 1.75,
        8: 2.00,
        9: 2.25,
        10: 2.50,
        11: 2.70,
        12: 3.00,   # Strongest growth — subscription model compounds
    },
}


# Monthly seasonality adjustments by calendar month (1 = January)
# Multiplier against baseline. US e-commerce averages.
MONTHLY_SEASONALITY = {
    1: 0.80,    # January: post-holiday slump, returns processing
    2: 0.85,    # February: slight recovery, Valentine's bump for some
    3: 0.90,    # March: spring shopping starts
    4: 0.95,    # April: steady
    5: 1.00,    # May: Mother's Day, baseline month
    6: 0.95,    # June: summer slowdown begins (outdoor > online)
    7: 0.90,    # July: Prime Day creates a spike but overall lower
    8: 0.95,    # August: back-to-school categories spike
    9: 1.00,    # September: fall shopping picks up
    10: 1.10,   # October: Q4 ramp begins, early holiday shoppers
    11: 1.30,   # November: Black Friday / Cyber Monday
    12: 1.35,   # December: holiday peak — highest sales month
}


# Typical ad spend ramp by month for new products
# Month 1 = testing phase (lower spend), then scale winners.
AD_SPEND_RAMP_BY_MONTH = {
    1: 0.60,    # Month 1: testing creatives and audiences — lower spend
    2: 0.80,    # Month 2: scaling initial winners
    3: 1.00,    # Month 3: full budget — you know what works
    4: 1.05,
    5: 1.10,
    6: 1.15,    # Month 6: slight increase as you find more audiences
    7: 1.15,
    8: 1.20,
    9: 1.20,
    10: 1.30,   # Month 10: Q4 ramp — increase for holiday season
    11: 1.50,   # Month 11: Black Friday push — highest ad spend
    12: 1.40,   # Month 12: holiday season — high but slightly below Nov
}


# Average ROAS (Return on Ad Spend) benchmarks by month
# New stores start with poor ROAS and improve as pixel learns.
ROAS_BENCHMARKS_BY_MONTH = {
    1: 1.5,     # Month 1: barely breaking even on ads
    2: 2.0,     # Month 2: pixel learning, audiences refining
    3: 2.5,     # Month 3: finding winning ads
    4: 3.0,     # Month 4: ad account maturing
    5: 3.2,
    6: 3.5,     # Month 6: established ad account
    7: 3.5,
    8: 3.5,
    9: 3.5,
    10: 3.0,    # Month 10: Q4 CPMs rise — ROAS dips
    11: 2.5,    # Month 11: highest competition — expensive clicks
    12: 2.8,    # Month 12: still elevated but slightly better than Nov
}


def get_growth_multiplier(category: str, month: int) -> float:
    """Get growth curve multiplier for a category at a given month."""
    curve = GROWTH_CURVE_BENCHMARKS.get(category, GROWTH_CURVE_BENCHMARKS["general"])
    return curve.get(min(month, 12), 1.0)


def get_seasonality_factor(calendar_month: int) -> float:
    """Get seasonality adjustment for a calendar month (1-12)."""
    return MONTHLY_SEASONALITY.get(calendar_month, 1.0)


def get_ad_spend_multiplier(store_month: int) -> float:
    """Get ad spend ramp multiplier for a given month of store operation."""
    return AD_SPEND_RAMP_BY_MONTH.get(min(store_month, 12), 1.0)


def project_ad_efficiency(
    monthly_ad_spend: float,
    category: str = "general",
    months: int = 12,
) -> list[dict[str, Any]]:
    """Project ad spend and expected ROAS over time.

    Returns monthly ad budget and expected revenue from ads.
    """
    projections = []
    for month in range(1, months + 1):
        spend_mult = AD_SPEND_RAMP_BY_MONTH.get(month, 1.0)
        roas = ROAS_BENCHMARKS_BY_MONTH.get(month, 3.0)
        month_spend = monthly_ad_spend * spend_mult
        expected_revenue = month_spend * roas

        projections.append({
            "month": month,
            "ad_spend": round(month_spend, 2),
            "expected_roas": roas,
            "expected_ad_revenue": round(expected_revenue, 2),
            "profitable_ads": roas > 2.0,
        })

    return projections
