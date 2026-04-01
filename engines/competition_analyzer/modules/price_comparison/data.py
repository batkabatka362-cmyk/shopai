"""
Price Comparison — Reference Data
===================================
Contains price distribution benchmarks by category, typical price ranges,
price-to-review correlation data, and price war indicator thresholds.
These serve as defaults when live market data is unavailable or incomplete.
"""

# --- Percentile Labels ---

PERCENTILE_LABELS = {
    "p25": 25,
    "p50": 50,
    "p75": 75,
}

# --- Category Price Benchmarks ---

CATEGORY_PRICE_BENCHMARKS = {
    "electronics": {
        "typical_median": 49.99,
        "budget_ceiling": 25.00,
        "premium_floor": 99.99,
        "avg_margin_pct": 25,
        "price_sensitivity": "high",
        "charm_pricing_effective": True,
    },
    "home_garden": {
        "typical_median": 34.99,
        "budget_ceiling": 15.00,
        "premium_floor": 79.99,
        "avg_margin_pct": 35,
        "price_sensitivity": "moderate",
        "charm_pricing_effective": True,
    },
    "beauty": {
        "typical_median": 24.99,
        "budget_ceiling": 10.00,
        "premium_floor": 59.99,
        "avg_margin_pct": 50,
        "price_sensitivity": "moderate",
        "charm_pricing_effective": True,
    },
    "clothing": {
        "typical_median": 29.99,
        "budget_ceiling": 12.00,
        "premium_floor": 69.99,
        "avg_margin_pct": 45,
        "price_sensitivity": "moderate",
        "charm_pricing_effective": True,
    },
    "toys_games": {
        "typical_median": 22.99,
        "budget_ceiling": 10.00,
        "premium_floor": 49.99,
        "avg_margin_pct": 40,
        "price_sensitivity": "high",
        "charm_pricing_effective": True,
    },
    "sports_outdoors": {
        "typical_median": 39.99,
        "budget_ceiling": 15.00,
        "premium_floor": 89.99,
        "avg_margin_pct": 30,
        "price_sensitivity": "moderate",
        "charm_pricing_effective": True,
    },
    "health_wellness": {
        "typical_median": 27.99,
        "budget_ceiling": 12.00,
        "premium_floor": 59.99,
        "avg_margin_pct": 55,
        "price_sensitivity": "low",
        "charm_pricing_effective": False,
    },
    "pet_supplies": {
        "typical_median": 19.99,
        "budget_ceiling": 8.00,
        "premium_floor": 44.99,
        "avg_margin_pct": 40,
        "price_sensitivity": "moderate",
        "charm_pricing_effective": True,
    },
    "office_products": {
        "typical_median": 18.99,
        "budget_ceiling": 7.00,
        "premium_floor": 49.99,
        "avg_margin_pct": 35,
        "price_sensitivity": "high",
        "charm_pricing_effective": True,
    },
    "luxury": {
        "typical_median": 149.99,
        "budget_ceiling": 75.00,
        "premium_floor": 299.99,
        "avg_margin_pct": 60,
        "price_sensitivity": "low",
        "charm_pricing_effective": False,
    },
}

# --- Typical Price Ranges ---

TYPICAL_PRICE_RANGES = {
    "impulse_buy": {"min": 1.00, "max": 20.00, "decision_time": "seconds"},
    "casual_purchase": {"min": 20.00, "max": 50.00, "decision_time": "minutes"},
    "considered_purchase": {"min": 50.00, "max": 150.00, "decision_time": "hours"},
    "significant_purchase": {"min": 150.00, "max": 500.00, "decision_time": "days"},
    "major_purchase": {"min": 500.00, "max": 5000.00, "decision_time": "weeks"},
}

# --- Price-to-Review Correlation Data ---

PRICE_REVIEW_CORRELATION = {
    "strong_negative": {
        "coefficient_range": (-1.0, -0.5),
        "meaning": "Lower prices strongly correlate with more reviews/sales.",
        "implication": "Price-sensitive market. Compete on price or add massive value.",
    },
    "moderate_negative": {
        "coefficient_range": (-0.5, -0.2),
        "meaning": "Some relationship between lower price and more sales.",
        "implication": "Price matters but is not the only factor. Balance price and value.",
    },
    "neutral": {
        "coefficient_range": (-0.2, 0.2),
        "meaning": "Price has little correlation with review volume.",
        "implication": "Other factors drive sales. Focus on product quality and marketing.",
    },
    "positive": {
        "coefficient_range": (0.2, 1.0),
        "meaning": "Higher prices correlate with more reviews/sales.",
        "implication": "Prestige market. Higher price may signal quality to buyers.",
    },
}

# --- Price War Indicators ---

PRICE_WAR_INDICATORS = {
    "severity_thresholds": {
        "mild": {"min_decline_pct": 2.0, "min_periods": 3},
        "moderate": {"min_decline_pct": 5.0, "min_periods": 1},
        "severe": {"min_decline_pct": 10.0, "min_periods": 1},
    },
    "warning_signals": [
        "Multiple competitors dropping prices in same period",
        "New entrant pricing significantly below market",
        "Market leader cutting price by more than 10%",
        "Average price declining for 3+ consecutive periods",
        "Competitors running simultaneous promotions",
    ],
    "response_strategies": {
        "hold": "Maintain price, increase perceived value, wait it out.",
        "selective_match": "Match on hero products, protect margins on the rest.",
        "differentiate": "Add features, bundles, or services competitors lack.",
        "retreat": "Exit the price segment and reposition upmarket.",
    },
    "typical_duration_weeks": {
        "mild": 4,
        "moderate": 8,
        "severe": 16,
    },
}

# --- Price Bucketing for Gap Analysis ---

PRICE_GAP_THRESHOLDS = {
    "significant_gap_pct": 15.0,
    "major_gap_pct": 30.0,
    "opportunity_gap_pct": 20.0,
}

# --- Margin Benchmarks by Business Model ---

MARGIN_BENCHMARKS = {
    "private_label": {"healthy": 40, "acceptable": 25, "critical": 15},
    "wholesale_resale": {"healthy": 25, "acceptable": 15, "critical": 8},
    "dropship": {"healthy": 20, "acceptable": 12, "critical": 5},
    "handmade": {"healthy": 55, "acceptable": 35, "critical": 20},
}
