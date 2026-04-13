"""Search volume reference data — conversion rates, benchmarks, and seasonal factors.

Provides:
  - Search-to-purchase conversion rates by product category
  - Search volume benchmarks for viability classification
  - Keyword intent classification weights
  - Seasonal search multipliers by month (1 = January .. 12 = December)
"""
from __future__ import annotations

from typing import Any


# Search-to-purchase conversion rates by category (full funnel breakdown)
CONVERSION_RATES_BY_CATEGORY: dict[str, dict[str, float]] = {
    "electronics":     {"search_to_click": 0.12, "click_to_visit": 0.65, "visit_to_cart": 0.08, "cart_to_purchase": 0.42, "overall": 0.020},
    "fashion":         {"search_to_click": 0.10, "click_to_visit": 0.60, "visit_to_cart": 0.07, "cart_to_purchase": 0.38, "overall": 0.015},
    "home_garden":     {"search_to_click": 0.11, "click_to_visit": 0.62, "visit_to_cart": 0.09, "cart_to_purchase": 0.40, "overall": 0.018},
    "health_beauty":   {"search_to_click": 0.13, "click_to_visit": 0.68, "visit_to_cart": 0.10, "cart_to_purchase": 0.45, "overall": 0.025},
    "sports_outdoors": {"search_to_click": 0.11, "click_to_visit": 0.63, "visit_to_cart": 0.08, "cart_to_purchase": 0.41, "overall": 0.019},
    "pet_supplies":    {"search_to_click": 0.14, "click_to_visit": 0.70, "visit_to_cart": 0.11, "cart_to_purchase": 0.48, "overall": 0.028},
    "toys_games":      {"search_to_click": 0.12, "click_to_visit": 0.64, "visit_to_cart": 0.09, "cart_to_purchase": 0.40, "overall": 0.017},
    "food_beverage":   {"search_to_click": 0.13, "click_to_visit": 0.66, "visit_to_cart": 0.10, "cart_to_purchase": 0.44, "overall": 0.023},
    "jewelry":         {"search_to_click": 0.09, "click_to_visit": 0.55, "visit_to_cart": 0.05, "cart_to_purchase": 0.35, "overall": 0.010},
    "baby":            {"search_to_click": 0.13, "click_to_visit": 0.67, "visit_to_cart": 0.10, "cart_to_purchase": 0.46, "overall": 0.026},
}

DEFAULT_CONVERSION_RATES: dict[str, float] = {
    "search_to_click": 0.11, "click_to_visit": 0.63,
    "visit_to_cart": 0.08, "cart_to_purchase": 0.40, "overall": 0.018,
}

# Search volume benchmarks (monthly searches)
SEARCH_VOLUME_BENCHMARKS: dict[str, dict[str, Any]] = {
    "high":         {"min": 10_000, "label": "High demand",              "competition": "heavy"},
    "medium":       {"min":  1_000, "label": "Moderate demand",          "competition": "moderate"},
    "low":          {"min":    200, "label": "Low demand — niche viable", "competition": "light"},
    "insufficient": {"min":      0, "label": "Too low — not viable",     "competition": "none"},
}

# Keyword intent weights — multiplier on base conversion rate
KEYWORD_INTENT_WEIGHTS: dict[str, float] = {
    "transactional": 2.5,   # "buy wireless earbuds", "cheap yoga mat"
    "commercial":    1.8,   # "best wireless earbuds 2024", "yoga mat reviews"
    "informational": 0.4,   # "how do wireless earbuds work"
    "navigational":  0.6,   # "Apple AirPods" — brand-specific, low capture
}

# Intent signal words for classification
INTENT_SIGNALS: dict[str, list[str]] = {
    "transactional": ["buy", "cheap", "discount", "deal", "order", "purchase", "price", "sale", "coupon", "shop"],
    "commercial":    ["best", "top", "review", "vs", "compare", "alternative", "recommended", "worth it", "guide"],
    "informational": ["how", "what", "why", "when", "tutorial", "learn", "tips", "ideas", "diy", "meaning"],
    "navigational":  ["amazon", "walmart", "ebay", "target", "official", "brand", "website", "app"],
}

# Seasonal search multipliers by month (1.0 = baseline average)
SEASONAL_MULTIPLIERS: dict[int, float] = {
    1: 0.85, 2: 0.80, 3: 0.90, 4: 0.95, 5: 1.00, 6: 0.95,
    7: 0.90, 8: 0.95, 9: 1.05, 10: 1.15, 11: 1.35, 12: 1.25,
}


def get_conversion_rate(category: str) -> dict[str, float]:
    """Get funnel conversion rates for a product category."""
    cat = category.lower().replace(" ", "_").replace("-", "_").replace("&", "_")
    return CONVERSION_RATES_BY_CATEGORY.get(cat, DEFAULT_CONVERSION_RATES)


def get_seasonal_multiplier(month: int) -> float:
    """Get seasonal search volume multiplier for a given month (1-12)."""
    return SEASONAL_MULTIPLIERS.get(month, 1.0)


def classify_intent(keyword: str) -> str:
    """Classify a keyword by search intent based on signal words."""
    kw_lower = keyword.lower()
    scores: dict[str, int] = {intent: 0 for intent in INTENT_SIGNALS}
    for intent, signals in INTENT_SIGNALS.items():
        for signal in signals:
            if signal in kw_lower:
                scores[intent] += 1
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best if scores[best] > 0 else "commercial"
