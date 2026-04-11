"""Market risk data — thresholds, benchmarks, and reference tables.

Contains:
  - Risk thresholds per dimension
  - Market maturity risk profiles
  - Competitive intensity benchmarks by category
  - Price erosion rates by category
"""
from __future__ import annotations

from typing import Any


# Risk thresholds per dimension — defines what "bad" looks like
RISK_THRESHOLDS = {
    "saturation_level": {
        "low": {"max_score": 25, "label": "Uncrowded — easy to get noticed"},
        "moderate": {"max_score": 50, "label": "Competitive but room exists"},
        "high": {"max_score": 75, "label": "Crowded — strong differentiation needed"},
        "critical": {"max_score": 100, "label": "Oversaturated — avoid unless unique"},
    },
    "demand_trend_direction": {
        "low": {"max_score": 25, "label": "Demand growing strongly"},
        "moderate": {"max_score": 50, "label": "Demand stable or slow growth"},
        "high": {"max_score": 75, "label": "Demand declining — caution"},
        "critical": {"max_score": 100, "label": "Demand collapsing — avoid"},
    },
    "competitive_intensity": {
        "low": {"max_score": 25, "label": "Fragmented — no dominant players"},
        "moderate": {"max_score": 50, "label": "Some strong players but room to compete"},
        "high": {"max_score": 75, "label": "Consolidated — top players dominate"},
        "critical": {"max_score": 100, "label": "Monopolistic — near impossible to enter"},
    },
    "price_erosion_rate": {
        "low": {"max_score": 25, "label": "Prices stable or rising"},
        "moderate": {"max_score": 50, "label": "Mild price pressure — manageable"},
        "high": {"max_score": 75, "label": "Prices dropping — margins shrinking"},
        "critical": {"max_score": 100, "label": "Race to bottom — unsustainable"},
    },
    "barrier_to_entry": {
        "low": {"max_score": 25, "label": "Easy entry — but also easy for competitors"},
        "moderate": {"max_score": 50, "label": "Some barriers — moderate protection"},
        "high": {"max_score": 75, "label": "High barriers — hard to enter but defensible"},
        "critical": {"max_score": 100, "label": "Extreme barriers — regulatory/capital heavy"},
    },
    "market_maturity_stage": {
        "low": {"max_score": 25, "label": "Growth phase — best time to enter"},
        "moderate": {"max_score": 50, "label": "Early maturity — still viable"},
        "high": {"max_score": 75, "label": "Mature market — incumbents entrenched"},
        "critical": {"max_score": 100, "label": "Declining lifecycle — exit, not entry"},
    },
}

# Market maturity profiles — risk characteristics at each lifecycle stage
MATURITY_RISK_PROFILES = {
    "emerging": {
        "age_range": (0, 2),
        "risk_level": "moderate",
        "characteristics": [
            "Unproven demand — could go either way",
            "Few competitors but also few customers",
            "High reward potential but high failure rate",
        ],
        "recommended_approach": "Validate with minimal investment, be ready to pivot",
    },
    "growth": {
        "age_range": (2, 5),
        "risk_level": "low",
        "characteristics": [
            "Demand proven and expanding",
            "New entrants welcome — market growing fast enough for all",
            "Mistakes forgiven by rising tide",
        ],
        "recommended_approach": "Enter aggressively, capture share while market expands",
    },
    "mature": {
        "age_range": (5, 12),
        "risk_level": "moderate_high",
        "characteristics": [
            "Growth slowing, competition intensifying",
            "Incumbents have brand loyalty and scale advantages",
            "Differentiation critical for survival",
        ],
        "recommended_approach": "Enter only with clear differentiation or cost advantage",
    },
    "declining": {
        "age_range": (12, 100),
        "risk_level": "high",
        "characteristics": [
            "Market shrinking — fewer customers each year",
            "Surviving players fight viciously for remaining share",
            "Innovation has moved elsewhere",
        ],
        "recommended_approach": "Avoid unless you can acquire a failing competitor cheaply",
    },
}

# Competitive intensity benchmarks by e-commerce category
COMPETITIVE_INTENSITY_BENCHMARKS = {
    "electronics": {"avg_competitors": 350, "top3_share_pct": 45, "intensity": "very_high"},
    "clothing": {"avg_competitors": 500, "top3_share_pct": 25, "intensity": "high"},
    "home_garden": {"avg_competitors": 200, "top3_share_pct": 30, "intensity": "moderate"},
    "health_beauty": {"avg_competitors": 300, "top3_share_pct": 35, "intensity": "high"},
    "sports_outdoors": {"avg_competitors": 180, "top3_share_pct": 30, "intensity": "moderate"},
    "pet_supplies": {"avg_competitors": 120, "top3_share_pct": 40, "intensity": "moderate"},
    "toys_games": {"avg_competitors": 150, "top3_share_pct": 50, "intensity": "high"},
    "food_beverage": {"avg_competitors": 100, "top3_share_pct": 35, "intensity": "moderate"},
    "jewelry": {"avg_competitors": 250, "top3_share_pct": 20, "intensity": "moderate"},
    "baby": {"avg_competitors": 130, "top3_share_pct": 45, "intensity": "high"},
}

# Annual price erosion rates by category (% decline per year)
PRICE_EROSION_RATES = {
    "electronics": 8.0,
    "clothing": 3.5,
    "home_garden": 2.0,
    "health_beauty": 1.5,
    "sports_outdoors": 2.5,
    "pet_supplies": 1.0,
    "toys_games": 4.0,
    "food_beverage": 0.5,
    "jewelry": 1.0,
    "baby": 3.0,
    "automotive": 2.0,
    "office_supplies": 5.0,
}


def get_price_erosion_rate(category: str) -> float:
    """Get the average annual price erosion rate for a category.

    Returns percentage (e.g., 8.0 means prices drop ~8% per year).
    """
    return PRICE_EROSION_RATES.get(category, 2.5)


def get_competitive_benchmark(category: str) -> dict[str, Any]:
    """Get competitive intensity benchmark for a category."""
    return COMPETITIVE_INTENSITY_BENCHMARKS.get(category, {
        "avg_competitors": 200,
        "top3_share_pct": 30,
        "intensity": "moderate",
    })


def get_maturity_profile(market_age_years: int) -> dict[str, Any]:
    """Get the maturity risk profile for a given market age."""
    for stage, profile in MATURITY_RISK_PROFILES.items():
        low, high = profile["age_range"]
        if low <= market_age_years < high:
            return {"stage": stage, **profile}
    return {"stage": "declining", **MATURITY_RISK_PROFILES["declining"]}
