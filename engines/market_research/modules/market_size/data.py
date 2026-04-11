"""Market size data structures — models for storing and retrieving market data.

Handles:
  - Market size estimates (TAM/SAM/SOM) persistence
  - Historical market size tracking (growth/decline detection)
  - Category benchmark storage
"""
from __future__ import annotations

import json
import os
import time
from typing import Any


# Growth rates by category (annual, estimated)
CATEGORY_GROWTH_RATES = {
    "electronics": 0.08,
    "clothing": 0.05,
    "home_garden": 0.07,
    "health_beauty": 0.12,
    "sports_outdoors": 0.09,
    "toys_games": 0.04,
    "pet_supplies": 0.15,
    "office_supplies": 0.02,
    "automotive": 0.06,
    "food_beverage": 0.18,
    "baby": 0.06,
    "jewelry": 0.07,
    "books": -0.02,
    "arts_crafts": 0.10,
}

# Average margins by category
CATEGORY_AVG_MARGINS = {
    "electronics": 0.15,
    "clothing": 0.45,
    "home_garden": 0.35,
    "health_beauty": 0.60,
    "sports_outdoors": 0.40,
    "toys_games": 0.35,
    "pet_supplies": 0.45,
    "office_supplies": 0.30,
    "automotive": 0.25,
    "food_beverage": 0.50,
    "baby": 0.40,
    "jewelry": 0.65,
    "books": 0.30,
    "arts_crafts": 0.55,
}


class MarketSizeRecord:
    """A single market size estimation record."""

    def __init__(
        self,
        category: str,
        tam: float,
        sam: float,
        som_typical: float,
        som_min: float = 0,
        som_max: float = 0,
        timestamp: float | None = None,
    ) -> None:
        self.category = category
        self.tam = tam
        self.sam = sam
        self.som_typical = som_typical
        self.som_min = som_min
        self.som_max = som_max
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "tam": self.tam,
            "sam": self.sam,
            "som_typical": self.som_typical,
            "som_min": self.som_min,
            "som_max": self.som_max,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketSizeRecord:
        return cls(
            category=data["category"],
            tam=data["tam"],
            sam=data["sam"],
            som_typical=data["som_typical"],
            som_min=data.get("som_min", 0),
            som_max=data.get("som_max", 0),
            timestamp=data.get("timestamp"),
        )


def get_category_growth(category: str) -> float:
    """Get annual growth rate for a category. Positive = growing."""
    return CATEGORY_GROWTH_RATES.get(category, 0.05)


def get_category_margin(category: str) -> float:
    """Get average margin for a category."""
    return CATEGORY_AVG_MARGINS.get(category, 0.35)


def project_market_size(current_tam: float, category: str, years: int = 3) -> list[dict[str, Any]]:
    """Project market size over N years using category growth rate."""
    growth_rate = get_category_growth(category)
    projections = []

    for year in range(1, years + 1):
        projected = current_tam * ((1 + growth_rate) ** year)
        projections.append({
            "year": year,
            "projected_tam": round(projected),
            "growth_rate": growth_rate,
            "cumulative_growth": round(((1 + growth_rate) ** year - 1) * 100, 1),
        })

    return projections
