"""Saturation data — benchmarks, thresholds, and category saturation levels."""
from __future__ import annotations

import time
from typing import Any


# Known category saturation levels (approximate, 2025)
CATEGORY_SATURATION_BENCHMARKS = {
    "phone_cases": {"saturation": 95, "competitors": 5000, "avg_margin": 12, "note": "Completely saturated — avoid"},
    "generic_tshirts": {"saturation": 90, "competitors": 3000, "avg_margin": 15, "note": "Race to bottom — avoid"},
    "yoga_mats": {"saturation": 75, "competitors": 800, "avg_margin": 25, "note": "Highly competitive — niche required"},
    "wireless_earbuds": {"saturation": 80, "competitors": 1200, "avg_margin": 18, "note": "Dominated by brands — avoid generic"},
    "dog_toys": {"saturation": 55, "competitors": 400, "avg_margin": 40, "note": "Competitive but viable — quality wins"},
    "resistance_bands": {"saturation": 65, "competitors": 600, "avg_margin": 35, "note": "Moderate — bundle strategy works"},
    "organic_skincare": {"saturation": 45, "competitors": 200, "avg_margin": 55, "note": "Growing niche — good margins"},
    "standing_desk_accessories": {"saturation": 30, "competitors": 80, "avg_margin": 40, "note": "Young market — opportunity"},
    "pet_supplements": {"saturation": 35, "competitors": 100, "avg_margin": 55, "note": "Growing fast — enter now"},
    "smart_home_sensors": {"saturation": 25, "competitors": 50, "avg_margin": 45, "note": "Emerging — technical expertise needed"},
    "personalized_jewelry": {"saturation": 40, "competitors": 300, "avg_margin": 60, "note": "Growing — customization is moat"},
    "eco_cleaning": {"saturation": 30, "competitors": 120, "avg_margin": 50, "note": "Growing trend — subscription opportunity"},
}

# Saturation level thresholds
SATURATION_THRESHOLDS = {
    "unsaturated": {"range": (0, 20), "entry_ease": "very_easy", "typical_competitors": "0-20"},
    "lightly_saturated": {"range": (20, 40), "entry_ease": "easy", "typical_competitors": "20-100"},
    "moderately_saturated": {"range": (40, 60), "entry_ease": "moderate", "typical_competitors": "100-500"},
    "highly_saturated": {"range": (60, 80), "entry_ease": "hard", "typical_competitors": "500-2000"},
    "oversaturated": {"range": (80, 100), "entry_ease": "extreme", "typical_competitors": "2000+"},
}

# CPC benchmarks by saturation level
CPC_BENCHMARKS = {
    "unsaturated": {"avg_cpc": 0.50, "range": (0.20, 1.00)},
    "lightly_saturated": {"avg_cpc": 1.00, "range": (0.50, 1.50)},
    "moderately_saturated": {"avg_cpc": 1.75, "range": (1.00, 2.50)},
    "highly_saturated": {"avg_cpc": 3.00, "range": (2.00, 5.00)},
    "oversaturated": {"avg_cpc": 5.00, "range": (3.00, 10.00)},
}


class SaturationRecord:
    """A point-in-time saturation measurement for tracking."""

    def __init__(
        self,
        category: str,
        saturation_index: int,
        level: str,
        competitor_count: int = 0,
        avg_margin: float = 0,
        timestamp: float | None = None,
    ) -> None:
        self.category = category
        self.saturation_index = saturation_index
        self.level = level
        self.competitor_count = competitor_count
        self.avg_margin = avg_margin
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "saturation_index": self.saturation_index,
            "level": self.level,
            "competitor_count": self.competitor_count,
            "avg_margin": self.avg_margin,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SaturationRecord:
        return cls(
            category=data["category"],
            saturation_index=data["saturation_index"],
            level=data["level"],
            competitor_count=data.get("competitor_count", 0),
            avg_margin=data.get("avg_margin", 0),
            timestamp=data.get("timestamp"),
        )


def get_category_benchmark(category: str) -> dict[str, Any] | None:
    """Get known saturation benchmark for a category."""
    cat = category.lower().replace(" ", "_").replace("-", "_")
    if cat in CATEGORY_SATURATION_BENCHMARKS:
        return CATEGORY_SATURATION_BENCHMARKS[cat]
    for key in CATEGORY_SATURATION_BENCHMARKS:
        if cat in key or key in cat:
            return CATEGORY_SATURATION_BENCHMARKS[key]
    return None


def get_cpc_benchmark(saturation_level: str) -> dict[str, Any]:
    """Get expected CPC range for a saturation level."""
    return CPC_BENCHMARKS.get(saturation_level, CPC_BENCHMARKS["moderately_saturated"])
