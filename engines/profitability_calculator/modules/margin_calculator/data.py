"""Margin data — category benchmarks, tier definitions, industry averages.

Real-world margin data for Shopify / e-commerce businesses.
Sources: Shopify benchmarks, industry reports, aggregated store data.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Category margin benchmarks (typical gross margin %)
# --------------------------------------------------------------------------- #
CATEGORY_MARGIN_BENCHMARKS: dict[str, dict[str, float]] = {
    "electronics":       {"gross": 15.0, "contribution": 10.0, "net": 5.0,  "operating": 8.0},
    "clothing":          {"gross": 50.0, "contribution": 38.0, "net": 15.0, "operating": 22.0},
    "health_beauty":     {"gross": 60.0, "contribution": 48.0, "net": 20.0, "operating": 30.0},
    "home_garden":       {"gross": 35.0, "contribution": 25.0, "net": 10.0, "operating": 18.0},
    "sports_outdoors":   {"gross": 40.0, "contribution": 30.0, "net": 12.0, "operating": 20.0},
    "pet_supplies":      {"gross": 45.0, "contribution": 35.0, "net": 14.0, "operating": 22.0},
    "toys_games":        {"gross": 35.0, "contribution": 25.0, "net": 10.0, "operating": 16.0},
    "food_beverage":     {"gross": 50.0, "contribution": 35.0, "net": 12.0, "operating": 20.0},
    "jewelry":           {"gross": 65.0, "contribution": 55.0, "net": 25.0, "operating": 35.0},
    "baby":              {"gross": 40.0, "contribution": 30.0, "net": 12.0, "operating": 18.0},
    "automotive":        {"gross": 25.0, "contribution": 18.0, "net": 8.0,  "operating": 12.0},
    "office_supplies":   {"gross": 30.0, "contribution": 22.0, "net": 9.0,  "operating": 14.0},
    "arts_crafts":       {"gross": 55.0, "contribution": 42.0, "net": 18.0, "operating": 28.0},
    "books":             {"gross": 30.0, "contribution": 20.0, "net": 7.0,  "operating": 12.0},
}

# --------------------------------------------------------------------------- #
#  Margin tier definitions
# --------------------------------------------------------------------------- #
MARGIN_TIERS: list[dict[str, Any]] = [
    {
        "tier": "premium",
        "min_pct": 60.0,
        "label": "Premium margin",
        "description": "Exceptional pricing power. Brand-driven or luxury positioning.",
        "typical_categories": ["jewelry", "health_beauty", "arts_crafts"],
    },
    {
        "tier": "healthy",
        "min_pct": 40.0,
        "label": "Healthy margin",
        "description": "Strong business fundamentals. Room for marketing spend and growth.",
        "typical_categories": ["clothing", "pet_supplies", "food_beverage"],
    },
    {
        "tier": "acceptable",
        "min_pct": 25.0,
        "label": "Acceptable margin",
        "description": "Viable but requires volume. Limited room for error.",
        "typical_categories": ["home_garden", "sports_outdoors", "toys_games"],
    },
    {
        "tier": "thin",
        "min_pct": 15.0,
        "label": "Thin margin",
        "description": "Razor-thin. One bad month erases a quarter of profit.",
        "typical_categories": ["electronics", "automotive"],
    },
    {
        "tier": "unsustainable",
        "min_pct": 0.0,
        "label": "Unsustainable margin",
        "description": "Cannot sustain operations. Immediate repricing or cost reduction needed.",
        "typical_categories": [],
    },
]

# --------------------------------------------------------------------------- #
#  Industry average margins by business model
# --------------------------------------------------------------------------- #
BUSINESS_MODEL_MARGINS: dict[str, dict[str, Any]] = {
    "dropshipping": {
        "typical_gross": (15.0, 25.0),
        "typical_net": (5.0, 10.0),
        "note": "Low barrier, low margin. Volume is king. Shipping times hurt retention.",
    },
    "private_label": {
        "typical_gross": (40.0, 60.0),
        "typical_net": (15.0, 25.0),
        "note": "Best balance of margin and control. Requires upfront inventory investment.",
    },
    "handmade": {
        "typical_gross": (50.0, 70.0),
        "typical_net": (20.0, 35.0),
        "note": "High margin but limited scale. Labor cost is the ceiling.",
    },
    "wholesale_resale": {
        "typical_gross": (25.0, 40.0),
        "typical_net": (8.0, 15.0),
        "note": "Moderate margins. Depends on supplier relationships and exclusivity.",
    },
    "print_on_demand": {
        "typical_gross": (20.0, 35.0),
        "typical_net": (8.0, 15.0),
        "note": "No inventory risk but base costs are high. Design differentiation is key.",
    },
    "subscription_box": {
        "typical_gross": (35.0, 55.0),
        "typical_net": (10.0, 20.0),
        "note": "Predictable revenue. Churn is the margin killer — retention > acquisition.",
    },
    "digital_products": {
        "typical_gross": (80.0, 95.0),
        "typical_net": (50.0, 80.0),
        "note": "Near-zero COGS after creation. Marketing is the only real variable cost.",
    },
}


def get_category_benchmark(category: str) -> dict[str, float]:
    """Return margin benchmarks for a category, with fallback defaults."""
    key = category.lower().replace(" ", "_").replace("-", "_").replace("&", "_")
    if key in CATEGORY_MARGIN_BENCHMARKS:
        return CATEGORY_MARGIN_BENCHMARKS[key]
    for k in CATEGORY_MARGIN_BENCHMARKS:
        if k in key or key in k:
            return CATEGORY_MARGIN_BENCHMARKS[k]
    return {"gross": 35.0, "contribution": 25.0, "net": 10.0, "operating": 18.0}


def get_tier(margin_pct: float) -> dict[str, Any]:
    """Classify a margin percentage into a tier."""
    for tier_def in MARGIN_TIERS:
        if margin_pct >= tier_def["min_pct"]:
            return tier_def
    return MARGIN_TIERS[-1]


def get_business_model_benchmark(model: str) -> dict[str, Any]:
    """Return typical margins for a business model."""
    key = model.lower().replace(" ", "_").replace("-", "_")
    return BUSINESS_MODEL_MARGINS.get(key, {
        "typical_gross": (25.0, 45.0),
        "typical_net": (8.0, 18.0),
        "note": "No specific data for this model. Using blended averages.",
    })
