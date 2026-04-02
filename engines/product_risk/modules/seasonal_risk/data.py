"""Seasonal Risk — reference data, profiles, and benchmarks.

Seasonality profiles by category, cash reserve requirements,
fad duration benchmarks, and weather impact factors.
"""
from __future__ import annotations

from typing import Any

# Peak-to-trough ratios and typical peak months for major categories
SEASONALITY_PROFILES: dict[str, dict[str, Any]] = {
    "holiday_gifts": {
        "peak_months": [11, 12],
        "trough_months": [1, 2, 6, 7],
        "peak_to_trough_ratio": 8.0,
        "classification": "highly_seasonal",
        "revenue_concentration": 0.55,
    },
    "outdoor_recreation": {
        "peak_months": [5, 6, 7, 8],
        "trough_months": [11, 12, 1, 2],
        "peak_to_trough_ratio": 5.5,
        "classification": "highly_seasonal",
        "revenue_concentration": 0.60,
    },
    "fitness_equipment": {
        "peak_months": [1, 2],
        "trough_months": [6, 7, 8],
        "peak_to_trough_ratio": 3.5,
        "classification": "moderate_seasonal",
        "revenue_concentration": 0.35,
    },
    "electronics": {
        "peak_months": [11, 12],
        "trough_months": [2, 3],
        "peak_to_trough_ratio": 2.5,
        "classification": "moderate_seasonal",
        "revenue_concentration": 0.30,
    },
    "home_essentials": {
        "peak_months": [],
        "trough_months": [],
        "peak_to_trough_ratio": 1.3,
        "classification": "non_seasonal",
        "revenue_concentration": 0.10,
    },
    "general": {
        "peak_months": [11, 12],
        "trough_months": [1, 2],
        "peak_to_trough_ratio": 2.0,
        "classification": "moderate_seasonal",
        "revenue_concentration": 0.25,
    },
}

CASH_RESERVE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "non_seasonal":      {"months_reserve": 2, "min_cash_ratio": 0.15},
    "moderate_seasonal":  {"months_reserve": 3, "min_cash_ratio": 0.25},
    "highly_seasonal":    {"months_reserve": 4, "min_cash_ratio": 0.40},
    "fad":               {"months_reserve": 1, "min_cash_ratio": 0.50},
}

FAD_DURATION_BENCHMARKS: dict[str, dict[str, Any]] = {
    "social_media_trend":  {"typical_months": 3, "max_months": 6, "exit_urgency": "high"},
    "viral_product":       {"typical_months": 4, "max_months": 8, "exit_urgency": "high"},
    "seasonal_fad":        {"typical_months": 2, "max_months": 4, "exit_urgency": "extreme"},
    "cultural_moment":     {"typical_months": 1, "max_months": 3, "exit_urgency": "extreme"},
    "celebrity_driven":    {"typical_months": 3, "max_months": 6, "exit_urgency": "high"},
}

WEATHER_IMPACT_FACTORS: dict[str, dict[str, float]] = {
    "outdoor_recreation": {"rain": -0.30, "heat_wave": 0.15, "cold_snap": -0.40, "snow": -0.50},
    "winter_sports":      {"rain": -0.10, "heat_wave": -0.60, "cold_snap": 0.25, "snow": 0.40},
    "beverages":          {"rain": -0.05, "heat_wave": 0.35, "cold_snap": -0.15, "snow": -0.10},
    "fashion_outerwear":  {"rain": 0.10, "heat_wave": -0.50, "cold_snap": 0.30, "snow": 0.20},
    "home_essentials":    {"rain": 0.0, "heat_wave": 0.05, "cold_snap": 0.05, "snow": 0.0},
    "general":            {"rain": -0.05, "heat_wave": -0.05, "cold_snap": -0.05, "snow": -0.05},
}

# Monthly demand weight index (1.0 = average month) for generic products
MONTHLY_DEMAND_INDEX: list[float] = [
    0.85, 0.80, 0.90, 0.95, 1.00, 1.00,
    0.95, 0.95, 1.05, 1.10, 1.30, 1.50,
]


def get_category_seasonality(category: str) -> dict[str, Any]:
    """Return the seasonality profile for a category, falling back to general."""
    key = category.lower().replace(" ", "_").replace("-", "_")
    return SEASONALITY_PROFILES.get(key, SEASONALITY_PROFILES["general"])


def get_weather_impact(category: str, weather_event: str) -> float:
    """Return the demand impact factor for a weather event on a category."""
    key = category.lower().replace(" ", "_").replace("-", "_")
    factors = WEATHER_IMPACT_FACTORS.get(key, WEATHER_IMPACT_FACTORS["general"])
    return factors.get(weather_event, 0.0)
