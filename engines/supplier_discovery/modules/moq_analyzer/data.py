"""
Reference data for MOQ analysis: typical MOQs, storage costs,
holding-cost percentages, and negotiation success rates.
"""

# ---------------------------------------------------------------------------
# Typical MOQs by product category and supplier type
# Values represent the most common minimum order quantities.
# ---------------------------------------------------------------------------
TYPICAL_MOQS = {
    "apparel": {
        "alibaba": 500,
        "wholesale": 24,
        "pod": 1,
    },
    "electronics_accessories": {
        "alibaba": 1000,
        "wholesale": 25,
        "pod": 1,
    },
    "home_decor": {
        "alibaba": 300,
        "wholesale": 12,
        "pod": 1,
    },
    "beauty_cosmetics": {
        "alibaba": 1000,
        "wholesale": 50,
        "pod": 1,
    },
    "jewelry": {
        "alibaba": 200,
        "wholesale": 10,
        "pod": 1,
    },
    "bags_luggage": {
        "alibaba": 500,
        "wholesale": 20,
        "pod": 1,
    },
    "kitchen_dining": {
        "alibaba": 500,
        "wholesale": 12,
        "pod": 1,
    },
    "toys_games": {
        "alibaba": 1000,
        "wholesale": 24,
        "pod": 1,
    },
    "pet_supplies": {
        "alibaba": 500,
        "wholesale": 12,
        "pod": 1,
    },
    "fitness_outdoor": {
        "alibaba": 300,
        "wholesale": 10,
        "pod": 1,
    },
}

# ---------------------------------------------------------------------------
# Storage cost per cubic foot per month (USD) by warehouse region
# ---------------------------------------------------------------------------
STORAGE_COST_PER_CUFT = {
    "us_west": 0.75,
    "us_east": 0.70,
    "us_central": 0.55,
    "eu_west": 0.85,
    "eu_east": 0.50,
    "uk": 0.90,
    "china_bonded": 0.30,
    "southeast_asia": 0.35,
    "australia": 0.95,
    "canada": 0.80,
}

# ---------------------------------------------------------------------------
# Annual inventory holding cost as a percentage of inventory value.
# Includes capital cost, insurance, shrinkage, and obsolescence.
# ---------------------------------------------------------------------------
HOLDING_COST_PCTS = {
    "low_risk": 0.18,       # stable, non-perishable goods
    "moderate_risk": 0.25,  # fashion, seasonal, or trend-driven
    "high_risk": 0.35,      # perishable, fast-changing tech accessories
}

# ---------------------------------------------------------------------------
# Average unit dimensions (cubic feet) by category — rough estimates
# ---------------------------------------------------------------------------
AVG_UNIT_VOLUME_CUFT = {
    "apparel": 0.25,
    "electronics_accessories": 0.10,
    "home_decor": 0.60,
    "beauty_cosmetics": 0.08,
    "jewelry": 0.02,
    "bags_luggage": 1.00,
    "kitchen_dining": 0.40,
    "toys_games": 0.50,
    "pet_supplies": 0.35,
    "fitness_outdoor": 0.80,
}

# ---------------------------------------------------------------------------
# MOQ negotiation success rates by requested reduction range.
# Based on aggregated seller survey data.
# ---------------------------------------------------------------------------
NEGOTIATION_SUCCESS_RATES = {
    "0_to_25_pct": 0.65,    # asking for up to 25% reduction
    "25_to_50_pct": 0.40,   # asking for 25-50% reduction
    "50_to_75_pct": 0.18,   # asking for 50-75% reduction
    "75_to_100_pct": 0.05,  # asking for 75%+ reduction (very unlikely)
}


def moq_for_category(category, supplier_type="alibaba"):
    """Look up typical MOQ; returns None if category/type unknown."""
    cat = TYPICAL_MOQS.get(category)
    if cat is None:
        return None
    return cat.get(supplier_type)


def holding_cost_for_risk(risk_level="moderate_risk"):
    """Return annual holding-cost percentage for the given risk level."""
    return HOLDING_COST_PCTS.get(risk_level, HOLDING_COST_PCTS["moderate_risk"])


def success_rate_for_reduction(reduction_pct):
    """Return the expected negotiation success rate for a given reduction %."""
    if reduction_pct <= 25:
        return NEGOTIATION_SUCCESS_RATES["0_to_25_pct"]
    if reduction_pct <= 50:
        return NEGOTIATION_SUCCESS_RATES["25_to_50_pct"]
    if reduction_pct <= 75:
        return NEGOTIATION_SUCCESS_RATES["50_to_75_pct"]
    return NEGOTIATION_SUCCESS_RATES["75_to_100_pct"]
