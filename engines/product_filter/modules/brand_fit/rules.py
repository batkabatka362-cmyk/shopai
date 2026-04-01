"""
rules.py — Brand coherence rules, quality tiers, and consistency constraints.

Defines the guardrails that keep a store's catalog on-brand.
"""

# ---------------------------------------------------------------------------
# Quality tiers and their expected price ranges
# ---------------------------------------------------------------------------
QUALITY_TIERS = {
    "budget": {"price_floor": 0, "price_ceiling": 25, "margin_min": 15, "rating_min": 3.0},
    "value": {"price_floor": 10, "price_ceiling": 60, "margin_min": 20, "rating_min": 3.5},
    "mid_range": {"price_floor": 25, "price_ceiling": 150, "margin_min": 25, "rating_min": 3.8},
    "premium": {"price_floor": 50, "price_ceiling": 500, "margin_min": 35, "rating_min": 4.0},
    "luxury": {"price_floor": 150, "price_ceiling": 99999, "margin_min": 45, "rating_min": 4.3},
}

# ---------------------------------------------------------------------------
# Core brand coherence rules
# ---------------------------------------------------------------------------
BRAND_COHERENCE_RULES = {
    "max_price_variance_factor": 3.0,
    "max_categories": 3,
    "max_categories_established": 6,
    "quality_tier_adjacency_max": 1,
    "min_brand_fit_score": 40,
    "min_catalog_overlap_pct": 30,
    "max_demographic_spread": 2,
}

MAX_CATEGORIES_NEW_STORE = 3

# ---------------------------------------------------------------------------
# Brand value compatibility matrix
# ---------------------------------------------------------------------------
BRAND_VALUE_COMPATIBILITY = {
    "eco_friendly": {
        "compatible": ["sustainable", "organic", "natural", "ethical", "minimalist"],
        "incompatible": ["fast_fashion", "disposable", "synthetic", "mass_produced"],
    },
    "premium": {
        "compatible": ["luxury", "artisan", "exclusive", "handcrafted", "limited_edition"],
        "incompatible": ["budget", "bulk", "generic", "clearance", "disposable"],
    },
    "budget": {
        "compatible": ["value", "everyday", "practical", "bulk", "accessible"],
        "incompatible": ["luxury", "exclusive", "artisan", "limited_edition"],
    },
    "niche": {
        "compatible": ["specialized", "expert", "curated", "enthusiast"],
        "incompatible": ["generic", "mass_market", "commodity"],
    },
    "lifestyle": {
        "compatible": ["aspirational", "trendy", "community", "wellness", "active"],
        "incompatible": ["utilitarian", "industrial", "commodity"],
    },
}

# ---------------------------------------------------------------------------
# Category affinity groups (categories that pair well together)
# ---------------------------------------------------------------------------
CATEGORY_AFFINITY = {
    "fitness": ["supplements", "activewear", "accessories", "equipment"],
    "beauty": ["cosmetics", "skincare", "haircare", "tools", "supplements"],
    "home": ["decor", "kitchen", "organization", "textiles", "candles"],
    "tech": ["electronics", "accessories", "gadgets", "cables", "cases"],
    "outdoor": ["camping", "hiking", "clothing", "tools", "survival"],
    "baby": ["clothing", "toys", "feeding", "safety", "nursery"],
    "pet": ["food", "toys", "accessories", "health", "grooming"],
}


def get_price_variance_limit(brand_archetype):
    """Return the max price variance factor for a given brand archetype.

    Premium and luxury brands need tighter price ranges; budget stores
    can tolerate wider variance.
    """
    limits = {
        "luxury": 2.0,
        "premium": 2.5,
        "mid_range": 3.0,
        "value": 4.0,
        "budget": 5.0,
    }
    return limits.get(brand_archetype, BRAND_COHERENCE_RULES["max_price_variance_factor"])


def get_tier_distance(tier_a, tier_b):
    """Return the number of tier steps between two quality tiers.

    Adjacent tiers (e.g. value-mid_range) return 1.  Same tier returns 0.
    """
    tier_order = ["budget", "value", "mid_range", "premium", "luxury"]
    try:
        idx_a = tier_order.index(tier_a)
        idx_b = tier_order.index(tier_b)
        return abs(idx_a - idx_b)
    except ValueError:
        return 0
