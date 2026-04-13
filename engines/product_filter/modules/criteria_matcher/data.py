"""
data.py — Category-specific defaults, price benchmarks, margin benchmarks.

These tables encode domain knowledge about what realistic thresholds
look like per product category so the filter can auto-tune when it
knows the category of a product batch.
"""

# ── Category-specific criteria defaults ───────────────────────────
# Each entry overrides the global default only for the listed keys.
CATEGORY_DEFAULTS = {
    "electronics": {
        "max_weight_kg": 3.0,
        "min_margin_pct": 18.0,
        "min_price": 15.0,
        "max_price": 500.0,
        "min_rating": 3.8,
        "min_review_count": 10,
    },
    "clothing": {
        "max_weight_kg": None,   # no weight limit for apparel
        "min_margin_pct": 40.0,
        "min_price": 8.0,
        "max_price": 120.0,
        "min_rating": 3.5,
        "min_review_count": 5,
    },
    "home_garden": {
        "max_weight_kg": 8.0,
        "min_margin_pct": 25.0,
        "min_price": 10.0,
        "max_price": 250.0,
        "min_rating": 3.5,
        "min_review_count": 5,
    },
    "beauty": {
        "max_weight_kg": 1.0,
        "min_margin_pct": 50.0,
        "min_price": 5.0,
        "max_price": 80.0,
        "min_rating": 4.0,
        "min_review_count": 15,
    },
    "toys": {
        "max_weight_kg": 3.0,
        "min_margin_pct": 30.0,
        "min_price": 8.0,
        "max_price": 60.0,
        "min_rating": 4.0,
        "min_review_count": 8,
    },
    "sports": {
        "max_weight_kg": 10.0,
        "min_margin_pct": 22.0,
        "min_price": 12.0,
        "max_price": 200.0,
        "min_rating": 3.5,
        "min_review_count": 5,
    },
    "pet_supplies": {
        "max_weight_kg": 6.0,
        "min_margin_pct": 30.0,
        "min_price": 5.0,
        "max_price": 80.0,
        "min_rating": 4.0,
        "min_review_count": 10,
    },
    "jewelry": {
        "max_weight_kg": 0.5,
        "min_margin_pct": 55.0,
        "min_price": 10.0,
        "max_price": 300.0,
        "min_rating": 4.0,
        "min_review_count": 8,
    },
}

# ── Price range benchmarks by category ────────────────────────────
# (low_typical, median, high_typical) — for sanity-checking outliers.
PRICE_BENCHMARKS = {
    "electronics":  {"low": 15.0,  "median": 45.0,  "high": 250.0},
    "clothing":     {"low": 8.0,   "median": 28.0,  "high": 75.0},
    "home_garden":  {"low": 12.0,  "median": 35.0,  "high": 150.0},
    "beauty":       {"low": 6.0,   "median": 22.0,  "high": 60.0},
    "toys":         {"low": 8.0,   "median": 20.0,  "high": 50.0},
    "sports":       {"low": 15.0,  "median": 40.0,  "high": 120.0},
    "pet_supplies": {"low": 5.0,   "median": 18.0,  "high": 55.0},
    "jewelry":      {"low": 12.0,  "median": 40.0,  "high": 200.0},
}

# ── Margin benchmarks by product type / sourcing method ───────────
# Realistic margin ranges when selling on Shopify via dropshipping,
# private label, or wholesale.
MARGIN_BENCHMARKS = {
    "dropshipping":   {"low": 15.0, "typical": 25.0, "high": 45.0},
    "private_label":  {"low": 30.0, "typical": 50.0, "high": 70.0},
    "wholesale":      {"low": 20.0, "typical": 35.0, "high": 55.0},
    "print_on_demand": {"low": 20.0, "typical": 35.0, "high": 50.0},
    "handmade":       {"low": 40.0, "typical": 60.0, "high": 80.0},
}


def get_category_criteria(category):
    """Return category-specific criteria, falling back to an empty dict.

    Parameters
    ----------
    category : str

    Returns
    -------
    dict  Criteria overrides for the given category.
    """
    key = category.lower().replace(" ", "_").replace("-", "_")
    return dict(CATEGORY_DEFAULTS.get(key, {}))


def is_price_outlier(price, category):
    """Check whether a price falls outside the typical range for its category.

    Returns
    -------
    str | None  A warning string if outlier, else None.
    """
    bench = PRICE_BENCHMARKS.get(category)
    if bench is None or price is None:
        return None
    if price < bench["low"] * 0.5:
        return f"Price ${price:.2f} is unusually low for {category} (typical low ${bench['low']:.2f})"
    if price > bench["high"] * 1.5:
        return f"Price ${price:.2f} is unusually high for {category} (typical high ${bench['high']:.2f})"
    return None


def expected_margin_range(sourcing_method):
    """Return the typical margin range for a sourcing method.

    Parameters
    ----------
    sourcing_method : str

    Returns
    -------
    dict | None  {low, typical, high} or None if unknown.
    """
    key = sourcing_method.lower().replace(" ", "_").replace("-", "_")
    bench = MARGIN_BENCHMARKS.get(key)
    return dict(bench) if bench else None
