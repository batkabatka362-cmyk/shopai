"""
data.py — Carrier rates, weight limits, surcharge tables, and restrictions.

All costs in USD.  Weight in kg, dimensions in cm.
"""


# ── Carrier weight and size limits ──────────────────────────────────────

CARRIER_LIMITS = {
    "usps": {
        "max_weight_kg": 31.75,
        "max_length_cm": 274,
        "max_combined_cm": 330,  # L + 2*(W+H)
    },
    "ups": {
        "max_weight_kg": 68.0,
        "max_length_cm": 274,
        "max_combined_cm": 419,
    },
    "fedex": {
        "max_weight_kg": 68.0,
        "max_length_cm": 274,
        "max_combined_cm": 419,
    },
    "dhl_express": {
        "max_weight_kg": 70.0,
        "max_length_cm": 300,
        "max_combined_cm": 420,
    },
}

DEFAULT_MAX_WEIGHT_KG = 30.0  # safe ceiling across most carriers


# ── Dimensional weight divisors (cm) ────────────────────────────────────

DIM_WEIGHT_DIVISORS = {
    "usps": 5000,
    "ups": 5000,
    "fedex": 5000,
    "dhl_express": 5000,
    "economy_sea": 6000,
}


# ── Shipping cost estimates by weight tier (domestic, USD) ──────────────

COST_BY_WEIGHT_TIER = {
    # (min_kg, max_kg): {method: cost}
    (0, 0.5): {"standard": 4.50, "express": 9.00, "overnight": 22.00},
    (0.5, 1): {"standard": 5.50, "express": 11.00, "overnight": 26.00},
    (1, 2):   {"standard": 7.00, "express": 14.00, "overnight": 32.00},
    (2, 5):   {"standard": 10.00, "express": 20.00, "overnight": 42.00},
    (5, 10):  {"standard": 16.00, "express": 30.00, "overnight": 58.00},
    (10, 20): {"standard": 24.00, "express": 45.00, "overnight": 80.00},
    (20, 30): {"standard": 35.00, "express": 65.00, "overnight": 110.00},
}


# ── Surcharges ──────────────────────────────────────────────────────────

SURCHARGES = {
    "oversized": 45.00,           # any single dimension > 120cm
    "additional_handling": 18.00,  # weight > 30kg or combined > 330cm
    "residential_delivery": 5.50,
    "hazmat_ground": 40.00,
    "hazmat_air": 75.00,
    "cold_chain_per_kg": 3.50,    # insulated + gel packs
    "fragile_packaging": 4.00,
}


# ── Hazmat categories ──────────────────────────────────────────────────

HAZMAT_CATEGORIES = {
    "lithium_ion": {
        "label": "Lithium-ion batteries",
        "ground_allowed": True,
        "air_allowed": False,
        "requires_documentation": True,
        "un_number": "UN3481",
    },
    "lithium_metal": {
        "label": "Lithium-metal batteries",
        "ground_allowed": True,
        "air_allowed": False,
        "requires_documentation": True,
        "un_number": "UN3091",
    },
    "flammable_liquid": {
        "label": "Flammable liquids (nail polish, perfume, etc.)",
        "ground_allowed": True,
        "air_allowed": False,
        "requires_documentation": True,
        "un_number": "UN1993",
    },
    "compressed_gas": {
        "label": "Compressed gas / aerosols",
        "ground_allowed": True,
        "air_allowed": False,
        "requires_documentation": True,
        "un_number": "UN1950",
    },
    "corrosive": {
        "label": "Corrosive substances",
        "ground_allowed": True,
        "air_allowed": False,
        "requires_documentation": True,
        "un_number": "UN1760",
    },
    "none": {
        "label": "Not hazmat",
        "ground_allowed": True,
        "air_allowed": True,
        "requires_documentation": False,
        "un_number": None,
    },
}


# ── International restrictions ──────────────────────────────────────────

INTERNATIONAL_RESTRICTIONS = {
    "AU": {"blocked_categories": ["flammable_liquid", "compressed_gas"]},
    "CA": {"blocked_categories": ["compressed_gas"]},
    "CN": {"blocked_categories": ["lithium_metal", "corrosive"]},
    "DE": {"blocked_categories": ["flammable_liquid"]},
    "GB": {"blocked_categories": ["compressed_gas", "corrosive"]},
    "JP": {"blocked_categories": ["flammable_liquid", "lithium_metal"]},
}

INTERNATIONAL_COST_MULTIPLIER = 2.5  # rough multiplier vs domestic


def get_shipping_cost_estimate(billable_weight_kg, method="standard"):
    """Look up estimated shipping cost for a given billable weight and method."""
    for (lo, hi), costs in COST_BY_WEIGHT_TIER.items():
        if lo <= billable_weight_kg < hi:
            return costs.get(method, costs["standard"])
    # Above highest tier — extrapolate linearly from the 20-30kg tier
    base = COST_BY_WEIGHT_TIER[(20, 30)].get(method, 35.00)
    extra_kg = billable_weight_kg - 30
    per_kg = 1.80 if method == "standard" else 3.50
    return base + extra_kg * per_kg


def get_hazmat_info(hazmat_class):
    """Return hazmat metadata for a classification string."""
    return HAZMAT_CATEGORIES.get(hazmat_class, HAZMAT_CATEGORIES["none"])
