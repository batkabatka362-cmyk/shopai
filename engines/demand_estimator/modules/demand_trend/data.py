"""Demand trend data — benchmarks, lifecycle positions, and adjustment factors.

Contains:
  - Trend velocity benchmarks (what's fast vs slow growth by category)
  - Category lifecycle positions (growth, mature, declining)
  - Seasonal adjustment factors for deseasonalizing data
  - Demand ceiling indicators
"""
from __future__ import annotations

from typing import Any


# Trend velocity benchmarks — monthly % change thresholds by category
# What counts as "rapid growth" varies by category maturity
TREND_VELOCITY_BENCHMARKS = {
    "general": {
        "rapid_growth": 8.0,       # >8%/month = rapid
        "moderate_growth": 3.0,    # 3-8%/month = moderate
        "slow_growth": 0.5,        # 0.5-3%/month = slow
        "stable": -2.0,            # -2% to 0.5% = stable
        "declining": -999,         # below -2% = declining
    },
    "electronics": {
        "rapid_growth": 10.0,
        "moderate_growth": 4.0,
        "slow_growth": 1.0,
        "stable": -3.0,
        "declining": -999,
    },
    "clothing": {
        "rapid_growth": 7.0,
        "moderate_growth": 3.0,
        "slow_growth": 0.5,
        "stable": -2.0,
        "declining": -999,
    },
    "health_beauty": {
        "rapid_growth": 8.0,
        "moderate_growth": 3.5,
        "slow_growth": 1.0,
        "stable": -2.0,
        "declining": -999,
    },
    "pet_supplies": {
        "rapid_growth": 10.0,
        "moderate_growth": 5.0,
        "slow_growth": 2.0,
        "stable": -1.0,
        "declining": -999,
    },
    "home_garden": {
        "rapid_growth": 8.0,
        "moderate_growth": 3.0,
        "slow_growth": 0.5,
        "stable": -2.0,
        "declining": -999,
    },
    "food_beverage": {
        "rapid_growth": 12.0,
        "moderate_growth": 5.0,
        "slow_growth": 1.5,
        "stable": -2.0,
        "declining": -999,
    },
}

# Category lifecycle positions — where each category sits in its growth curve
CATEGORY_LIFECYCLE_POSITIONS = {
    "electronics": {
        "stage": "mature",
        "description": "Large, mature market. Growth comes from new sub-categories.",
        "growth_ceiling_factor": 0.75,
        "typical_annual_growth_pct": 8,
    },
    "clothing": {
        "stage": "mature",
        "description": "Highly mature market. Growth from niches and brand differentiation.",
        "growth_ceiling_factor": 0.70,
        "typical_annual_growth_pct": 5,
    },
    "health_beauty": {
        "stage": "growth",
        "description": "Strong growth phase. Clean beauty and wellness driving expansion.",
        "growth_ceiling_factor": 0.90,
        "typical_annual_growth_pct": 12,
    },
    "pet_supplies": {
        "stage": "early_growth",
        "description": "Fastest growing e-commerce category. Pet humanization trend.",
        "growth_ceiling_factor": 0.95,
        "typical_annual_growth_pct": 15,
    },
    "home_garden": {
        "stage": "growth",
        "description": "Post-COVID growth stabilizing. Smart home driving new demand.",
        "growth_ceiling_factor": 0.85,
        "typical_annual_growth_pct": 7,
    },
    "sports_outdoors": {
        "stage": "growth",
        "description": "Wellness trend driving growth. Home fitness remains strong.",
        "growth_ceiling_factor": 0.88,
        "typical_annual_growth_pct": 9,
    },
    "food_beverage": {
        "stage": "early_growth",
        "description": "Online grocery and specialty food booming. Subscription models work.",
        "growth_ceiling_factor": 0.95,
        "typical_annual_growth_pct": 18,
    },
    "toys_games": {
        "stage": "mature",
        "description": "Mature with seasonal spikes. STEM and educational toys growing.",
        "growth_ceiling_factor": 0.70,
        "typical_annual_growth_pct": 4,
    },
    "jewelry": {
        "stage": "mature",
        "description": "Mature market. Personalization and sustainable materials trending.",
        "growth_ceiling_factor": 0.75,
        "typical_annual_growth_pct": 7,
    },
    "books": {
        "stage": "declining",
        "description": "Declining physical book market. Digital and niche categories stable.",
        "growth_ceiling_factor": 0.50,
        "typical_annual_growth_pct": -2,
    },
    "office_supplies": {
        "stage": "declining",
        "description": "Declining as workplaces go digital. Home office niche still viable.",
        "growth_ceiling_factor": 0.55,
        "typical_annual_growth_pct": 2,
    },
}

# Seasonal adjustment factors — divide raw data by these to deseasonalize
# Index 0 = January, Index 11 = December
SEASONAL_ADJUSTMENT_FACTORS = {
    "general": [
        0.82, 0.85, 0.92, 0.96, 1.00, 0.98,
        0.93, 0.96, 1.02, 1.08, 1.25, 1.45,
    ],
    "electronics": [
        0.70, 0.72, 0.82, 0.88, 0.92, 0.95,
        0.88, 0.92, 1.00, 1.12, 1.45, 1.75,
    ],
    "clothing": [
        0.75, 0.78, 0.92, 1.00, 1.05, 0.98,
        0.88, 0.95, 1.08, 1.04, 1.30, 1.48,
    ],
    "health_beauty": [
        1.08, 0.92, 0.95, 1.00, 1.02, 0.98,
        0.92, 0.95, 1.00, 1.00, 1.08, 1.18,
    ],
    "home_garden": [
        0.62, 0.68, 0.92, 1.15, 1.22, 1.18,
        1.08, 1.00, 0.95, 0.88, 0.92, 1.00,
    ],
    "pet_supplies": [
        0.88, 0.88, 0.92, 0.96, 1.00, 1.00,
        1.00, 1.00, 1.02, 1.04, 1.12, 1.28,
    ],
}

# Demand ceiling indicators — signals that demand is plateauing
DEMAND_CEILING_INDICATORS = {
    "growth_deceleration": {
        "description": "Growth rate has slowed for 3+ consecutive months",
        "weight": 0.35,
    },
    "search_volume_plateau": {
        "description": "Keyword search volume has stopped growing",
        "weight": 0.25,
    },
    "market_saturation": {
        "description": "Number of competitors increasing while demand is flat",
        "weight": 0.20,
    },
    "price_erosion": {
        "description": "Average selling prices declining — sign of commoditization",
        "weight": 0.20,
    },
}


def get_velocity_benchmark(category: str) -> dict[str, float]:
    """Get trend velocity benchmarks for a category."""
    cat_key = category.lower().replace(" ", "_")
    return TREND_VELOCITY_BENCHMARKS.get(
        cat_key, TREND_VELOCITY_BENCHMARKS["general"]
    )


def get_lifecycle_position(category: str) -> dict[str, Any]:
    """Get lifecycle position for a category."""
    cat_key = category.lower().replace(" ", "_")
    return CATEGORY_LIFECYCLE_POSITIONS.get(cat_key, {
        "stage": "unknown",
        "description": "No lifecycle data available for this category",
        "growth_ceiling_factor": 0.80,
        "typical_annual_growth_pct": 5,
    })


def get_seasonal_factor(category: str, month: int) -> float:
    """Get seasonal adjustment factor for a category and month.

    Args:
        category: Product category
        month: Month of year (1-12)

    Returns:
        Multiplier (1.0 = average, >1 = above average, <1 = below average)
    """
    cat_key = category.lower().replace(" ", "_")
    factors = SEASONAL_ADJUSTMENT_FACTORS.get(
        cat_key, SEASONAL_ADJUSTMENT_FACTORS["general"]
    )
    month_idx = max(0, min(11, month - 1))
    return factors[month_idx]
