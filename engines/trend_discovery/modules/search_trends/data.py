"""Search trends data — keyword benchmarks and historical patterns."""
from __future__ import annotations
from typing import Any

# Keyword difficulty tiers
KEYWORD_DIFFICULTY = {
    "very_easy": {"kd_range": (0, 20), "typical_time_to_rank": "2-4 weeks", "content_needed": "Basic product page"},
    "easy": {"kd_range": (20, 40), "typical_time_to_rank": "1-3 months", "content_needed": "Optimized product page + 1 blog post"},
    "medium": {"kd_range": (40, 60), "typical_time_to_rank": "3-6 months", "content_needed": "Product page + 3-5 blog posts + backlinks"},
    "hard": {"kd_range": (60, 80), "typical_time_to_rank": "6-12 months", "content_needed": "Extensive content hub + authority backlinks"},
    "very_hard": {"kd_range": (80, 100), "typical_time_to_rank": "12+ months", "content_needed": "Major content investment + brand authority"},
}

# Average CPC by category (USD)
CATEGORY_CPC_BENCHMARKS = {
    "electronics": 1.50, "clothing": 0.80, "health_beauty": 1.20, "home_garden": 0.90,
    "pet_supplies": 0.75, "fitness": 1.30, "jewelry": 1.80, "toys": 0.60,
    "food_beverage": 0.70, "office": 1.00, "automotive": 1.40, "baby": 0.85,
}

# Seasonal search patterns (multiplier by month, Jan=0)
SEARCH_SEASONALITY = {
    "gift": [0.8, 1.5, 0.7, 0.8, 1.2, 0.9, 0.7, 0.7, 0.8, 0.9, 1.3, 2.0],
    "fitness": [2.0, 1.5, 1.1, 0.9, 0.8, 0.7, 0.7, 0.8, 1.0, 0.9, 0.8, 0.9],
    "outdoor": [0.6, 0.7, 1.0, 1.3, 1.5, 1.6, 1.5, 1.3, 1.0, 0.8, 0.5, 0.4],
    "back_to_school": [0.5, 0.5, 0.5, 0.6, 0.7, 1.0, 1.8, 2.0, 1.5, 0.7, 0.5, 0.5],
}

def get_keyword_difficulty_info(kd_score: int) -> dict[str, Any]:
    for level, info in KEYWORD_DIFFICULTY.items():
        if kd_score <= info["kd_range"][1]:
            return {"level": level, **info}
    return {"level": "very_hard", **KEYWORD_DIFFICULTY["very_hard"]}

def get_category_cpc(category: str) -> float:
    cat = category.lower().replace(" ", "_")
    return CATEGORY_CPC_BENCHMARKS.get(cat, 1.00)
