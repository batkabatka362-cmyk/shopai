"""Seasonality data — monthly sales patterns by category.

Each pattern is a list of 12 values (Jan-Dec), normalized so average = 100.
Values represent relative sales volume:
  - 100 = average month
  - 150 = 50% above average
  - 70 = 30% below average

Data sources: Shopify ecosystem reports, Google Trends patterns,
Amazon seasonal data, industry reports.
"""
from __future__ import annotations

from typing import Any


# Monthly index patterns (Jan=index[0], Dec=index[11])
CATEGORY_SEASONAL_PATTERNS = {
    # Electronics: Q4 heavy (Black Friday + Christmas gifts)
    "electronics": [75, 70, 80, 85, 85, 80, 75, 90, 95, 100, 150, 215],

    # Clothing: Spring + Fall peaks (new season launches)
    "clothing": [80, 80, 110, 120, 110, 90, 85, 95, 120, 115, 100, 95],

    # Health & Beauty: Jan peak (resolutions), steady otherwise
    "health_beauty": [140, 120, 105, 100, 95, 90, 85, 90, 100, 95, 90, 90],

    # Fitness: January spike, summer dip
    "fitness": [200, 150, 110, 90, 85, 75, 70, 75, 95, 85, 80, 85],

    # Pet Supplies: Very stable, slight holiday bump
    "pet_supplies": [95, 90, 95, 100, 100, 95, 95, 100, 100, 100, 110, 120],

    # Home & Garden: Spring peak (home improvement season)
    "home_garden": [80, 85, 110, 130, 140, 120, 100, 95, 90, 85, 80, 85],

    # Toys & Games: Extreme Q4 (Christmas-dominant)
    "toys_games": [60, 50, 55, 60, 65, 70, 75, 80, 85, 90, 140, 270],

    # Outdoor/Sports: Summer peak
    "sports_outdoors": [75, 80, 100, 120, 140, 150, 145, 130, 100, 80, 50, 30],

    # Jewelry: Valentine's + Christmas dual peaks
    "jewelry": [80, 150, 85, 90, 110, 95, 80, 85, 90, 85, 100, 150],

    # Food & Beverage: Holiday peaks + steady baseline
    "food_beverage": [90, 85, 90, 95, 95, 95, 100, 95, 100, 100, 120, 135],

    # Baby: Stable with slight spring bump (baby shower season)
    "baby": [95, 95, 105, 110, 110, 105, 100, 100, 100, 95, 90, 95],

    # Office Supplies: Back-to-school + January
    "office_supplies": [120, 100, 90, 85, 85, 80, 90, 140, 130, 90, 80, 110],

    # Arts & Crafts: Holiday season (gift-making)
    "arts_crafts": [90, 85, 90, 90, 85, 80, 80, 85, 100, 120, 140, 155],

    # Swimwear: Extreme seasonality
    "swimwear": [50, 60, 100, 150, 200, 220, 180, 120, 50, 30, 20, 20],

    # Winter Clothing: Inverse of swimwear
    "winter_clothing": [150, 140, 100, 60, 30, 20, 20, 30, 80, 130, 170, 170],

    # Wedding: Spring/Summer peak
    "wedding": [70, 80, 110, 140, 160, 160, 140, 120, 100, 60, 30, 30],

    # Automotive: Spring peak (road trip season prep)
    "automotive": [85, 90, 110, 120, 120, 110, 105, 100, 95, 85, 80, 100],

    # Books: Holiday gifting + back to school
    "books": [90, 85, 85, 90, 85, 80, 80, 110, 120, 90, 100, 185],

    # Supplements: January resolution + steady
    "supplements": [160, 130, 105, 95, 90, 85, 80, 85, 95, 90, 85, 100],
}

# Weekly patterns (day of week, Monday=0)
WEEKLY_PATTERNS = {
    "general_ecommerce": {
        "Monday": 105,
        "Tuesday": 110,
        "Wednesday": 108,
        "Thursday": 105,
        "Friday": 95,
        "Saturday": 85,
        "Sunday": 92,
        "insight": "Tuesday-Wednesday peak (payday processing, weekend research → weekday purchase)",
    },
    "impulse_purchases": {
        "Monday": 90,
        "Tuesday": 95,
        "Wednesday": 100,
        "Thursday": 105,
        "Friday": 110,
        "Saturday": 110,
        "Sunday": 90,
        "insight": "Friday-Saturday peak (weekend browsing + impulse buying)",
    },
    "b2b_products": {
        "Monday": 120,
        "Tuesday": 125,
        "Wednesday": 120,
        "Thursday": 110,
        "Friday": 90,
        "Saturday": 20,
        "Sunday": 15,
        "insight": "Mon-Wed peak (business hours purchasing)",
    },
}

# Monthly pay cycle effects
PAYDAY_EFFECTS = {
    "first_of_month": {
        "days": [1, 2, 3],
        "lift_pct": 15,
        "note": "Many people paid on 1st — spending spike",
    },
    "mid_month": {
        "days": [14, 15, 16],
        "lift_pct": 10,
        "note": "Bi-weekly payday — smaller spike",
    },
    "end_of_month": {
        "days": [28, 29, 30, 31],
        "lift_pct": -10,
        "note": "End of month — budgets tightest, spending dips",
    },
}


def get_seasonal_pattern(category: str) -> list[float]:
    """Get monthly sales pattern for a category."""
    cat = category.lower().replace(" ", "_").replace("-", "_")
    if cat in CATEGORY_SEASONAL_PATTERNS:
        return CATEGORY_SEASONAL_PATTERNS[cat]
    for key in CATEGORY_SEASONAL_PATTERNS:
        if cat in key or key in cat:
            return CATEGORY_SEASONAL_PATTERNS[key]
    return [85, 80, 90, 95, 95, 90, 85, 90, 95, 100, 130, 165]  # Default


def get_weekly_pattern(product_type: str = "general_ecommerce") -> dict[str, Any]:
    """Get weekly sales pattern."""
    return WEEKLY_PATTERNS.get(product_type, WEEKLY_PATTERNS["general_ecommerce"])


def get_payday_effects() -> dict[str, Any]:
    """Get monthly pay cycle effects on sales."""
    return PAYDAY_EFFECTS


def list_all_categories() -> list[str]:
    """List all categories with seasonal data."""
    return sorted(CATEGORY_SEASONAL_PATTERNS.keys())
