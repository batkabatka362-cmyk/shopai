"""Market trends data — trend history tracking and storage.

Stores trend snapshots over time to detect momentum shifts,
seasonal patterns, and long-term direction changes.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any


# Known trending categories (2024-2026 data, manually curated)
TRENDING_CATEGORIES_2025 = {
    "wellness_supplements": {
        "search_growth_pct": 45,
        "social_mentions_growth": 120,
        "review_volume_growth": 35,
        "new_products_launched": 85,
        "price_trend_pct": 5,
        "notes": "Post-COVID health focus continues",
    },
    "sustainable_fashion": {
        "search_growth_pct": 60,
        "social_mentions_growth": 200,
        "review_volume_growth": 25,
        "new_products_launched": 120,
        "price_trend_pct": 8,
        "notes": "Gen Z driving demand, premium pricing accepted",
    },
    "smart_home_devices": {
        "search_growth_pct": 30,
        "social_mentions_growth": 40,
        "review_volume_growth": 45,
        "new_products_launched": 60,
        "price_trend_pct": -5,
        "notes": "Growing but prices declining as market matures",
    },
    "pet_wellness": {
        "search_growth_pct": 55,
        "social_mentions_growth": 80,
        "review_volume_growth": 50,
        "new_products_launched": 40,
        "price_trend_pct": 10,
        "notes": "Pet humanization trend — premium products thriving",
    },
    "home_office": {
        "search_growth_pct": -15,
        "social_mentions_growth": -20,
        "review_volume_growth": -5,
        "new_products_launched": 15,
        "price_trend_pct": -10,
        "notes": "Post-COVID normalization, market declining from peak",
    },
    "ai_tools_accessories": {
        "search_growth_pct": 300,
        "social_mentions_growth": 500,
        "review_volume_growth": 10,
        "new_products_launched": 200,
        "price_trend_pct": 15,
        "notes": "AI hype — explosive but potentially unsustainable",
    },
    "outdoor_adventure": {
        "search_growth_pct": 25,
        "social_mentions_growth": 50,
        "review_volume_growth": 30,
        "new_products_launched": 35,
        "price_trend_pct": 3,
        "notes": "Steady growth, lifestyle-driven",
    },
    "minimalist_jewelry": {
        "search_growth_pct": 35,
        "social_mentions_growth": 90,
        "review_volume_growth": 40,
        "new_products_launched": 50,
        "price_trend_pct": 5,
        "notes": "Instagram/TikTok driven, high margins",
    },
}

# Seasonal trend modifiers (which months are strongest)
SEASONAL_TREND_MODIFIERS = {
    "wellness_supplements": {"peak_months": [1, 2, 9], "dip_months": [6, 7], "modifier": 1.3},
    "sustainable_fashion": {"peak_months": [3, 4, 9, 10], "dip_months": [1, 2], "modifier": 1.2},
    "smart_home_devices": {"peak_months": [11, 12], "dip_months": [6, 7, 8], "modifier": 1.5},
    "pet_wellness": {"peak_months": [3, 4, 8], "dip_months": [], "modifier": 1.1},
    "outdoor_adventure": {"peak_months": [4, 5, 6, 7], "dip_months": [11, 12, 1, 2], "modifier": 1.4},
}


class TrendSnapshot:
    """A point-in-time trend measurement."""

    def __init__(
        self,
        category: str,
        trend_score: float,
        trend_level: str,
        signals: dict[str, Any],
        timestamp: float | None = None,
    ) -> None:
        self.category = category
        self.trend_score = trend_score
        self.trend_level = trend_level
        self.signals = signals
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "trend_score": self.trend_score,
            "trend_level": self.trend_level,
            "signals": self.signals,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrendSnapshot:
        return cls(
            category=data["category"],
            trend_score=data["trend_score"],
            trend_level=data["trend_level"],
            signals=data.get("signals", {}),
            timestamp=data.get("timestamp"),
        )


def get_known_trending(category: str | None = None) -> dict[str, Any]:
    """Get pre-loaded trending category data."""
    if category:
        key = category.lower().replace(" ", "_").replace("-", "_")
        if key in TRENDING_CATEGORIES_2025:
            return {key: TRENDING_CATEGORIES_2025[key]}
        # Fuzzy match
        for k, v in TRENDING_CATEGORIES_2025.items():
            if key in k or k in key:
                return {k: v}
        return {}
    return TRENDING_CATEGORIES_2025


def get_seasonal_modifier(category: str, month: int) -> float:
    """Get seasonal trend modifier for a category in a given month."""
    key = category.lower().replace(" ", "_").replace("-", "_")
    seasonal = SEASONAL_TREND_MODIFIERS.get(key)
    if not seasonal:
        return 1.0
    if month in seasonal.get("peak_months", []):
        return seasonal["modifier"]
    if month in seasonal.get("dip_months", []):
        return 1.0 / seasonal["modifier"]
    return 1.0
