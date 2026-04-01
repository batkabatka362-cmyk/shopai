"""
rules.py — Default criteria thresholds and goal-based overrides.

Central place to define what "good enough" means for product filtering
and how those thresholds shift depending on the business goal.
"""

# ── Default criteria (balanced strategy) ───────────────────────────
DEFAULT_CRITERIA = {
    "min_margin_pct": 20.0,
    "min_price": 10.0,
    "max_price": 200.0,
    "max_weight_kg": 5.0,
    "min_rating": 3.5,
    "min_review_count": 5,
    "allowed_categories": None,  # None means all categories allowed
}

# ── Goal-specific overrides ────────────────────────────────────────
# "growth"  — cast a wider net, accept lower margins
# "profit"  — tighter filters, only high-margin winners
# "test"    — very loose, let almost everything through for A/B tests
GOAL_OVERRIDES = {
    "growth": {
        "min_margin_pct": 12.0,
        "min_price": 5.0,
        "max_price": 300.0,
        "max_weight_kg": 8.0,
        "min_rating": 3.0,
        "min_review_count": 2,
    },
    "profit": {
        "min_margin_pct": 35.0,
        "min_price": 20.0,
        "max_price": 150.0,
        "max_weight_kg": 3.0,
        "min_rating": 4.0,
        "min_review_count": 10,
    },
    "test": {
        "min_margin_pct": 5.0,
        "min_price": 1.0,
        "max_price": 500.0,
        "max_weight_kg": 15.0,
        "min_rating": 2.0,
        "min_review_count": 0,
    },
}

# ── Absolute hard limits (safety rails) ───────────────────────────
# No matter how loose the goal, these are never crossed.
HARD_LIMITS = {
    "min_margin_pct_floor": 3.0,
    "max_weight_kg_ceiling": 30.0,
    "min_price_floor": 0.50,
    "max_price_ceiling": 2000.0,
    "min_rating_floor": 1.0,
}


def get_criteria_for_goal(goal):
    """Return a merged criteria dict for the given goal.

    Falls back to DEFAULT_CRITERIA for any key not overridden by the
    goal.  Unknown goals return defaults unchanged.

    Parameters
    ----------
    goal : str | None

    Returns
    -------
    dict
    """
    base = dict(DEFAULT_CRITERIA)
    overrides = GOAL_OVERRIDES.get(goal, {})
    base.update(overrides)
    return base


def validate_criteria(criteria):
    """Clamp user-supplied criteria to hard limits.

    Returns a new dict with values clipped so they stay within safe
    boundaries.  This prevents accidentally filtering out everything
    or letting garbage products through.

    Parameters
    ----------
    criteria : dict

    Returns
    -------
    dict  Validated criteria.
    list  Warnings about clamped values.
    """
    validated = dict(criteria)
    warnings = []

    floor = HARD_LIMITS["min_margin_pct_floor"]
    if validated.get("min_margin_pct") is not None:
        if validated["min_margin_pct"] < floor:
            warnings.append(
                f"min_margin_pct {validated['min_margin_pct']}% clamped to floor {floor}%"
            )
            validated["min_margin_pct"] = floor

    ceil = HARD_LIMITS["max_weight_kg_ceiling"]
    if validated.get("max_weight_kg") is not None:
        if validated["max_weight_kg"] > ceil:
            warnings.append(
                f"max_weight_kg {validated['max_weight_kg']}kg clamped to ceiling {ceil}kg"
            )
            validated["max_weight_kg"] = ceil

    price_floor = HARD_LIMITS["min_price_floor"]
    if validated.get("min_price") is not None:
        if validated["min_price"] < price_floor:
            warnings.append(
                f"min_price ${validated['min_price']} clamped to floor ${price_floor}"
            )
            validated["min_price"] = price_floor

    price_ceil = HARD_LIMITS["max_price_ceiling"]
    if validated.get("max_price") is not None:
        if validated["max_price"] > price_ceil:
            warnings.append(
                f"max_price ${validated['max_price']} clamped to ceiling ${price_ceil}"
            )
            validated["max_price"] = price_ceil

    rating_floor = HARD_LIMITS["min_rating_floor"]
    if validated.get("min_rating") is not None:
        if validated["min_rating"] < rating_floor:
            validated["min_rating"] = rating_floor

    return validated, warnings
