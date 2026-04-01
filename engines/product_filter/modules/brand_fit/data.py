"""
data.py — Brand archetype definitions, target demographics, brand value keywords.

Provides the reference profiles that brand_fit scoring compares against.
"""

# ---------------------------------------------------------------------------
# Brand archetypes with full profile definitions
# ---------------------------------------------------------------------------
BRAND_ARCHETYPES = {
    "premium": {
        "description": "High-quality, aspirational products with strong margins",
        "price_tier": "premium",
        "target_margin_pct": 45,
        "min_rating": 4.0,
        "values": ["quality", "exclusive", "artisan", "premium", "luxury"],
        "tone": "sophisticated",
        "max_categories": 4,
        "customer_loyalty": "high",
    },
    "value": {
        "description": "Reliable products at competitive prices",
        "price_tier": "value",
        "target_margin_pct": 25,
        "min_rating": 3.5,
        "values": ["affordable", "practical", "everyday", "value", "accessible"],
        "tone": "friendly",
        "max_categories": 5,
        "customer_loyalty": "medium",
    },
    "eco": {
        "description": "Sustainable, environmentally conscious products",
        "price_tier": "mid_range",
        "target_margin_pct": 35,
        "min_rating": 3.8,
        "values": ["eco_friendly", "sustainable", "organic", "natural", "ethical"],
        "tone": "authentic",
        "max_categories": 4,
        "customer_loyalty": "high",
    },
    "niche": {
        "description": "Specialized products for an enthusiast audience",
        "price_tier": "mid_range",
        "target_margin_pct": 40,
        "min_rating": 4.0,
        "values": ["specialized", "expert", "curated", "enthusiast", "niche"],
        "tone": "authoritative",
        "max_categories": 2,
        "customer_loyalty": "very_high",
    },
    "lifestyle": {
        "description": "Trend-forward products that define a way of living",
        "price_tier": "mid_range",
        "target_margin_pct": 35,
        "min_rating": 3.8,
        "values": ["aspirational", "trendy", "community", "active", "lifestyle"],
        "tone": "inspiring",
        "max_categories": 5,
        "customer_loyalty": "medium",
    },
    "budget": {
        "description": "Lowest price, highest volume, minimal frills",
        "price_tier": "budget",
        "target_margin_pct": 18,
        "min_rating": 3.0,
        "values": ["cheap", "bulk", "practical", "disposable", "accessible"],
        "tone": "direct",
        "max_categories": 6,
        "customer_loyalty": "low",
    },
}

# ---------------------------------------------------------------------------
# Target demographic profiles
# ---------------------------------------------------------------------------
TARGET_DEMOGRAPHICS = {
    "gen_z": {"age_range": (18, 27), "price_sensitivity": "high", "values": ["trendy", "sustainable", "digital_native"]},
    "millennial": {"age_range": (28, 43), "price_sensitivity": "medium", "values": ["quality", "experience", "wellness"]},
    "gen_x": {"age_range": (44, 59), "price_sensitivity": "low", "values": ["reliability", "premium", "family"]},
    "boomer": {"age_range": (60, 78), "price_sensitivity": "low", "values": ["trust", "quality", "tradition"]},
    "parents": {"age_range": (25, 45), "price_sensitivity": "medium", "values": ["safety", "value", "practical"]},
    "fitness": {"age_range": (18, 50), "price_sensitivity": "medium", "values": ["performance", "health", "active"]},
    "professional": {"age_range": (25, 55), "price_sensitivity": "low", "values": ["premium", "efficiency", "quality"]},
}

# ---------------------------------------------------------------------------
# Brand value keywords for matching product attributes to brand identity
# ---------------------------------------------------------------------------
BRAND_VALUE_KEYWORDS = {
    "eco_friendly": ["organic", "recycled", "biodegradable", "sustainable", "plant-based", "zero-waste", "compostable"],
    "premium": ["handcrafted", "artisan", "limited-edition", "luxury", "exclusive", "bespoke", "curated"],
    "budget": ["affordable", "bulk", "economy", "value-pack", "clearance", "discount", "basic"],
    "health": ["natural", "non-toxic", "wellness", "therapeutic", "vitamin", "supplement", "organic"],
    "tech": ["smart", "wireless", "bluetooth", "AI", "digital", "automated", "connected"],
    "family": ["kid-friendly", "family-size", "safe", "educational", "durable", "washable"],
    "minimalist": ["simple", "clean", "essential", "basic", "functional", "understated"],
}


def get_archetype_profile(archetype):
    """Return the full profile for a brand archetype, defaulting to 'value'."""
    return BRAND_ARCHETYPES.get(archetype, BRAND_ARCHETYPES["value"])
