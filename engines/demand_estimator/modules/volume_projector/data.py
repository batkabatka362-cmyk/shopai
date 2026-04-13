"""Volume projector data — growth ramps, thresholds, and benchmarks.

Contains:
  - Growth ramp by category (month 1-12 multipliers)
  - Minimum viable volume thresholds per category
  - Inventory coverage benchmarks
  - Seasonal adjustment factors by category and month
"""
from __future__ import annotations

from typing import Any


# Growth ramp multipliers by category — what % of steady-state volume to expect
# Month 1 = 40% of steady state (new product ramp), reaching 100% by month 6-9
# Some categories ramp faster (impulse buys) vs slower (considered purchases)
GROWTH_RAMP_BY_CATEGORY = {
    "general": {
        1: 0.40, 2: 0.55, 3: 0.65, 4: 0.75, 5: 0.85,
        6: 0.90, 7: 0.95, 8: 0.97, 9: 1.00, 10: 1.00,
        11: 1.00, 12: 1.00,
    },
    "electronics": {
        1: 0.35, 2: 0.50, 3: 0.60, 4: 0.72, 5: 0.82,
        6: 0.88, 7: 0.93, 8: 0.96, 9: 1.00, 10: 1.00,
        11: 1.00, 12: 1.00,
    },
    "clothing": {
        1: 0.45, 2: 0.60, 3: 0.72, 4: 0.82, 5: 0.90,
        6: 0.95, 7: 0.98, 8: 1.00, 9: 1.00, 10: 1.00,
        11: 1.00, 12: 1.00,
    },
    "health_beauty": {
        1: 0.40, 2: 0.55, 3: 0.68, 4: 0.78, 5: 0.87,
        6: 0.93, 7: 0.97, 8: 1.00, 9: 1.00, 10: 1.00,
        11: 1.00, 12: 1.00,
    },
    "home_garden": {
        1: 0.35, 2: 0.48, 3: 0.58, 4: 0.68, 5: 0.78,
        6: 0.86, 7: 0.92, 8: 0.96, 9: 1.00, 10: 1.00,
        11: 1.00, 12: 1.00,
    },
    "pet_supplies": {
        1: 0.45, 2: 0.62, 3: 0.75, 4: 0.85, 5: 0.92,
        6: 0.96, 7: 0.98, 8: 1.00, 9: 1.00, 10: 1.00,
        11: 1.00, 12: 1.00,
    },
    "sports_outdoors": {
        1: 0.38, 2: 0.52, 3: 0.63, 4: 0.74, 5: 0.84,
        6: 0.90, 7: 0.95, 8: 0.98, 9: 1.00, 10: 1.00,
        11: 1.00, 12: 1.00,
    },
    "food_beverage": {
        1: 0.50, 2: 0.65, 3: 0.78, 4: 0.88, 5: 0.94,
        6: 0.97, 7: 1.00, 8: 1.00, 9: 1.00, 10: 1.00,
        11: 1.00, 12: 1.00,
    },
}

# Minimum viable volume thresholds — below these, the product isn't worth selling
MINIMUM_VIABLE_VOLUME = {
    "general":         {"min_monthly_units": 30, "good_monthly_units": 100, "excellent_monthly_units": 300},
    "electronics":     {"min_monthly_units": 25, "good_monthly_units": 80,  "excellent_monthly_units": 250},
    "clothing":        {"min_monthly_units": 40, "good_monthly_units": 150, "excellent_monthly_units": 500},
    "health_beauty":   {"min_monthly_units": 35, "good_monthly_units": 120, "excellent_monthly_units": 400},
    "home_garden":     {"min_monthly_units": 25, "good_monthly_units": 80,  "excellent_monthly_units": 250},
    "pet_supplies":    {"min_monthly_units": 30, "good_monthly_units": 100, "excellent_monthly_units": 350},
    "sports_outdoors": {"min_monthly_units": 25, "good_monthly_units": 80,  "excellent_monthly_units": 200},
    "food_beverage":   {"min_monthly_units": 50, "good_monthly_units": 200, "excellent_monthly_units": 600},
    "jewelry":         {"min_monthly_units": 15, "good_monthly_units": 50,  "excellent_monthly_units": 150},
}

# Inventory coverage benchmarks — how much stock to hold, when to reorder
INVENTORY_COVERAGE_BENCHMARKS = {
    "general":         {"coverage_months": 2.0, "buffer_pct": 0.30, "reorder_threshold_pct": 0.60},
    "electronics":     {"coverage_months": 2.0, "buffer_pct": 0.25, "reorder_threshold_pct": 0.60},
    "clothing":        {"coverage_months": 2.5, "buffer_pct": 0.35, "reorder_threshold_pct": 0.55},
    "health_beauty":   {"coverage_months": 2.0, "buffer_pct": 0.30, "reorder_threshold_pct": 0.60},
    "home_garden":     {"coverage_months": 2.5, "buffer_pct": 0.30, "reorder_threshold_pct": 0.60},
    "pet_supplies":    {"coverage_months": 2.0, "buffer_pct": 0.30, "reorder_threshold_pct": 0.60},
    "food_beverage":   {"coverage_months": 1.5, "buffer_pct": 0.20, "reorder_threshold_pct": 0.65},
    "jewelry":         {"coverage_months": 3.0, "buffer_pct": 0.25, "reorder_threshold_pct": 0.55},
}

# Seasonal adjustment factors by category — multiplier for each month (Jan=0, Dec=11)
# 1.0 = average month, >1.0 = above average, <1.0 = below average
SEASONAL_ADJUSTMENTS = {
    "general": [
        0.75, 0.80, 0.90, 0.95, 1.00, 1.00,
        0.90, 0.95, 1.05, 1.10, 1.30, 1.50,
    ],
    "electronics": [
        0.65, 0.70, 0.80, 0.85, 0.90, 0.95,
        0.85, 0.90, 1.00, 1.10, 1.50, 1.80,
    ],
    "clothing": [
        0.70, 0.75, 0.90, 1.00, 1.05, 1.00,
        0.85, 0.95, 1.10, 1.05, 1.35, 1.50,
    ],
    "health_beauty": [
        1.10, 0.90, 0.95, 1.00, 1.05, 1.00,
        0.90, 0.95, 1.00, 1.00, 1.10, 1.20,
    ],
    "home_garden": [
        0.60, 0.65, 0.90, 1.15, 1.25, 1.20,
        1.10, 1.00, 0.95, 0.85, 0.90, 1.00,
    ],
    "pet_supplies": [
        0.85, 0.85, 0.90, 0.95, 1.00, 1.00,
        1.00, 1.00, 1.05, 1.05, 1.15, 1.30,
    ],
}


def get_growth_multiplier(category: str, product_age_months: int) -> float:
    """Get the growth ramp multiplier for a given category and product age.

    Returns a value between 0.35 and 1.0.
    """
    cat_key = category.lower().replace(" ", "_")
    ramp = GROWTH_RAMP_BY_CATEGORY.get(cat_key, GROWTH_RAMP_BY_CATEGORY["general"])
    # Clamp month to 1-12 range
    month = max(1, min(12, product_age_months)) if product_age_months > 0 else 1
    return ramp.get(month, 1.0)


def get_inventory_coverage(category: str) -> dict[str, float]:
    """Get inventory coverage benchmarks for a category."""
    cat_key = category.lower().replace(" ", "_")
    return INVENTORY_COVERAGE_BENCHMARKS.get(
        cat_key, INVENTORY_COVERAGE_BENCHMARKS["general"]
    )
