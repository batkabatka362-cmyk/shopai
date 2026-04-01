"""
Scenario Modeler — Reference data.

Probability distributions by product type, typical variance ranges,
and correlation factors between business variables for realistic
scenario generation.
"""

# Scenario probability distributions by product type.
# Each entry defines how likely each scenario tier is and the
# typical multiplier range for that product category.
SCENARIO_DISTRIBUTIONS = {
    "physical_product": {
        "pessimistic": {"probability": 0.20, "multiplier_range": (0.40, 0.60)},
        "expected":    {"probability": 0.55, "multiplier_range": (0.85, 1.15)},
        "optimistic":  {"probability": 0.25, "multiplier_range": (1.30, 1.70)},
        "volatility": "medium",
        "seasonal_factor": 1.15,
    },
    "digital_product": {
        "pessimistic": {"probability": 0.25, "multiplier_range": (0.30, 0.55)},
        "expected":    {"probability": 0.45, "multiplier_range": (0.80, 1.20)},
        "optimistic":  {"probability": 0.30, "multiplier_range": (1.40, 2.00)},
        "volatility": "high",
        "seasonal_factor": 1.05,
    },
    "subscription": {
        "pessimistic": {"probability": 0.15, "multiplier_range": (0.55, 0.70)},
        "expected":    {"probability": 0.60, "multiplier_range": (0.90, 1.10)},
        "optimistic":  {"probability": 0.25, "multiplier_range": (1.20, 1.50)},
        "volatility": "low",
        "seasonal_factor": 1.02,
    },
    "service": {
        "pessimistic": {"probability": 0.20, "multiplier_range": (0.50, 0.65)},
        "expected":    {"probability": 0.55, "multiplier_range": (0.85, 1.15)},
        "optimistic":  {"probability": 0.25, "multiplier_range": (1.25, 1.60)},
        "volatility": "medium",
        "seasonal_factor": 1.08,
    },
    "marketplace": {
        "pessimistic": {"probability": 0.30, "multiplier_range": (0.25, 0.50)},
        "expected":    {"probability": 0.40, "multiplier_range": (0.75, 1.25)},
        "optimistic":  {"probability": 0.30, "multiplier_range": (1.50, 2.50)},
        "volatility": "very_high",
        "seasonal_factor": 1.10,
    },
}

# Typical variance ranges for key business variables.
# Expressed as (lower_bound_pct, upper_bound_pct) relative to base.
VARIANCE_RANGES = {
    "volume": {
        "range_pct": (-50, 50),
        "description": "Unit sales can swing 50% in either direction",
        "confidence_80": (-30, 30),
        "confidence_95": (-50, 50),
    },
    "price": {
        "range_pct": (-20, 20),
        "description": "Pricing typically varies within 20% of target",
        "confidence_80": (-10, 10),
        "confidence_95": (-20, 20),
    },
    "costs": {
        "range_pct": (-15, 15),
        "description": "Cost variations generally stay within 15%",
        "confidence_80": (-8, 8),
        "confidence_95": (-15, 15),
    },
    "ad_spend_efficiency": {
        "range_pct": (-40, 40),
        "description": "Ad ROI is highly variable, especially early on",
        "confidence_80": (-25, 25),
        "confidence_95": (-40, 40),
    },
    "conversion_rate": {
        "range_pct": (-35, 35),
        "description": "Conversion rates fluctuate with traffic quality",
        "confidence_80": (-20, 20),
        "confidence_95": (-35, 35),
    },
    "churn_rate": {
        "range_pct": (-25, 60),
        "description": "Churn can spike sharply but rarely drops much",
        "confidence_80": (-15, 35),
        "confidence_95": (-25, 60),
    },
}

# Correlation factors between variables.
# Positive = variables move together; negative = inverse relationship.
# Values range from -1.0 to 1.0.
CORRELATION_FACTORS = {
    ("price", "volume"):              -0.60,
    ("ad_spend", "volume"):            0.45,
    ("ad_spend", "conversion_rate"):   0.30,
    ("price", "margin"):               0.70,
    ("volume", "costs"):               0.85,
    ("volume", "revenue"):             0.95,
    ("churn_rate", "volume"):         -0.50,
    ("price", "churn_rate"):           0.35,
    ("ad_spend", "revenue"):           0.55,
    ("conversion_rate", "revenue"):    0.80,
    ("costs", "margin"):              -0.75,
    ("volume", "margin"):              0.40,
}


def get_distribution_for_product_type(product_type):
    """
    Look up the scenario distribution for a given product type.
    Falls back to physical_product defaults if type is unknown.

    Returns dict with pessimistic/expected/optimistic probability
    distributions and volatility metadata.
    """
    if product_type in SCENARIO_DISTRIBUTIONS:
        return SCENARIO_DISTRIBUTIONS[product_type]
    return SCENARIO_DISTRIBUTIONS["physical_product"]


def get_variance_range(variable, confidence=80):
    """
    Get the variance range for a variable at a given confidence level.

    Parameters:
        variable: one of the VARIANCE_RANGES keys
        confidence: 80 or 95 (percent confidence interval)

    Returns tuple (lower_pct, upper_pct) or default (-30, 30).
    """
    entry = VARIANCE_RANGES.get(variable)
    if not entry:
        return (-30, 30)
    if confidence >= 95:
        return tuple(entry["confidence_95"])
    return tuple(entry["confidence_80"])


def get_correlation(var_a, var_b):
    """
    Look up the correlation factor between two variables.
    Checks both orderings. Returns 0.0 if no correlation data exists.
    """
    key = (var_a, var_b)
    if key in CORRELATION_FACTORS:
        return CORRELATION_FACTORS[key]
    reverse_key = (var_b, var_a)
    if reverse_key in CORRELATION_FACTORS:
        return CORRELATION_FACTORS[reverse_key]
    return 0.0


def apply_correlation_adjustment(base_value, change_pct, correlated_var_change, correlation):
    """
    Adjust a variable's projected change based on its correlation
    with another variable that has already changed.

    For example, if volume drops 30% and volume-cost correlation is 0.85,
    costs should also decrease by 30% * 0.85 = 25.5%.

    Returns the adjusted value.
    """
    correlated_adjustment = correlated_var_change * correlation
    total_change = change_pct + correlated_adjustment
    return base_value * (1 + total_change / 100)
