"""
Competitor Finder — Reference Data & Benchmarks
=================================================
Static data used for scoring competitors, interpreting market concentration,
and contextualizing store maturity and review significance.
"""

# ---------------------------------------------------------------------------
# Herfindahl-Hirschman Index (HHI) thresholds
# Based on US DOJ / FTC Horizontal Merger Guidelines.
# HHI ranges from 0 (perfect competition) to 10000 (monopoly).
# ---------------------------------------------------------------------------
HHI_THRESHOLDS = {
    "unconcentrated": 1500,       # Below 1500 = competitive market
    "moderate": 2500,             # 1500-2500 = moderately concentrated
    "highly_concentrated": 2500,  # Above 2500 = highly concentrated / oligopoly
}

HHI_INTERPRETATION = {
    "below_1500": (
        "The market is unconcentrated. Many players compete and no single "
        "seller dominates. Entry is generally feasible."
    ),
    "1500_to_2500": (
        "The market is moderately concentrated. A few mid-size players hold "
        "significant share. New entrants face moderate barriers."
    ),
    "above_2500": (
        "The market is highly concentrated. One or two dominant sellers "
        "control most revenue. Competing head-on is very difficult."
    ),
}

# ---------------------------------------------------------------------------
# Competitive Strength Scoring Weights
# Each factor contributes to a 0-1.0 composite score.
# Weights must sum to 1.0.
# ---------------------------------------------------------------------------
STRENGTH_SCORING_WEIGHTS = {
    "revenue": 0.30,       # Estimated monthly/annual revenue
    "reviews": 0.25,       # Total review count (proxy for sales volume)
    "rating": 0.20,        # Average customer rating (quality signal)
    "store_age": 0.15,     # Years the store has been active
    "product_count": 0.10, # Breadth of product catalog
}

STRENGTH_LABELS = {
    (0.0, 0.2):  "very_weak",
    (0.2, 0.4):  "weak",
    (0.4, 0.6):  "moderate",
    (0.6, 0.8):  "strong",
    (0.8, 1.01): "dominant",
}


def get_strength_label(score):
    """Return a human-readable label for a numeric strength score."""
    for (low, high), label in STRENGTH_LABELS.items():
        if low <= score < high:
            return label
    return "unknown"


# ---------------------------------------------------------------------------
# Store Age Maturity Benchmarks (in years)
# ---------------------------------------------------------------------------
STORE_AGE_BENCHMARKS = {
    "new": 0.5,          # Less than 6 months — brand new, unproven
    "emerging": 1.0,     # 6-12 months — building traction
    "established": 2.0,  # 1-2 years — has a track record
    "mature": 3.0,       # 3+ years — strong moat, repeat customers
    "veteran": 5.0,      # 5+ years — deeply entrenched
}

STORE_AGE_INTERPRETATION = {
    "new": "Very new store, still building reputation. Vulnerable to quality issues.",
    "emerging": "Growing store with some traction. May lack repeat customer base.",
    "established": "Proven store with a track record. Has baseline customer trust.",
    "mature": "Well-established with likely repeat customers and brand recognition.",
    "veteran": "Long-standing player with deep marketplace knowledge and loyal base.",
}


def get_store_maturity(age_years):
    """Return the maturity tier for a given store age in years."""
    if age_years < STORE_AGE_BENCHMARKS["new"]:
        return "new"
    elif age_years < STORE_AGE_BENCHMARKS["emerging"]:
        return "emerging"
    elif age_years < STORE_AGE_BENCHMARKS["established"]:
        return "established"
    elif age_years < STORE_AGE_BENCHMARKS["mature"]:
        return "mature"
    return "veteran"


# ---------------------------------------------------------------------------
# Review Count Significance Thresholds
# ---------------------------------------------------------------------------
REVIEW_COUNT_THRESHOLDS = {
    "negligible": 10,     # Fewer than 10 — too few to draw conclusions
    "low": 50,            # 10-50 — some signal, still early
    "moderate": 200,      # 50-200 — meaningful customer feedback
    "high": 1000,         # 200-1000 — well-validated product
    "very_high": 5000,    # 1000+ — best-seller territory
}

REVIEW_SIGNIFICANCE = {
    "negligible": "Too few reviews to assess product quality reliably.",
    "low": "Limited reviews. Product is either new or low-volume.",
    "moderate": "Decent review base. Customers have validated the product.",
    "high": "Strong review count indicating consistent sales volume.",
    "very_high": "Best-seller level reviews. This product dominates its niche.",
}


def get_review_significance(count):
    """Return the significance tier for a given review count."""
    if count < REVIEW_COUNT_THRESHOLDS["negligible"]:
        return "negligible"
    elif count < REVIEW_COUNT_THRESHOLDS["low"]:
        return "low"
    elif count < REVIEW_COUNT_THRESHOLDS["moderate"]:
        return "moderate"
    elif count < REVIEW_COUNT_THRESHOLDS["high"]:
        return "high"
    return "very_high"


# ---------------------------------------------------------------------------
# Market Concentration Benchmarks — used by logic.assess_competitive_landscape
# ---------------------------------------------------------------------------
MARKET_CONCENTRATION_BENCHMARKS = {
    "crowded_direct_min": 8,          # 8+ direct competitors = crowded
    "crowded_avg_strength": 0.5,      # average strength >= 0.5 in crowded
    "open_direct_max": 3,             # 3 or fewer directs = open
    "open_avg_strength": 0.35,        # average strength < 0.35 in open
    "moderate_min_competitors": 3,    # lower bound for moderate assessment
}
