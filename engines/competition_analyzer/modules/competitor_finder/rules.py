"""
Competitor Finder — Rules & Validation
========================================
Business rules for competitor identification, classification thresholds,
and data validation constraints.
"""

# Minimum number of competitors required for a reliable analysis.
# Below this threshold the module returns an error rather than unreliable results.
MIN_COMPETITORS_FOR_ANALYSIS = 3

# Maximum competitors to analyze in a single run to keep processing bounded.
MAX_COMPETITORS_ANALYZED = 100

# Price tolerance percentage for "similar price range" matching.
# A competitor is price-comparable if their price is within ±30% of the reference.
PRICE_RANGE_TOLERANCE = 0.30

# Criteria bundle used when classifying direct competitors.
DIRECT_COMPETITOR_CRITERIA = {
    "same_category": True,
    "price_tolerance": PRICE_RANGE_TOLERANCE,
    "min_keyword_overlap": 0.0,
}

# HHI-based concentration thresholds (US DOJ / FTC standard breakpoints).
# HHI below 1500 = unconcentrated, 1500-2500 = moderate, above 2500 = high.
CONCENTRATION_THRESHOLDS = {
    "unconcentrated_max": 1500,
    "moderate_max": 2500,
    "high_min": 2500,
}

# Required fields every competitor record must contain to pass validation.
REQUIRED_COMPETITOR_FIELDS = [
    "name",
    "product_category",
    "price",
]

# Optional but recommended fields for richer analysis.
RECOMMENDED_COMPETITOR_FIELDS = [
    "estimated_revenue",
    "review_count",
    "rating",
    "store_age_years",
    "product_count",
    "marketplace",
    "keywords",
]


def validate_competitor_data(competitor):
    """
    Check that a competitor record has all required fields and that values
    are within acceptable ranges.

    Returns True if the record is valid, False otherwise.
    """
    if not isinstance(competitor, dict):
        return False

    for field in REQUIRED_COMPETITOR_FIELDS:
        if field not in competitor or competitor[field] is None:
            return False

    price = competitor.get("price", 0)
    if not isinstance(price, (int, float)) or price < 0:
        return False

    rating = competitor.get("rating")
    if rating is not None:
        if not isinstance(rating, (int, float)) or rating < 0 or rating > 5:
            return False

    review_count = competitor.get("review_count")
    if review_count is not None:
        if not isinstance(review_count, (int, float)) or review_count < 0:
            return False

    store_age = competitor.get("store_age_years")
    if store_age is not None:
        if not isinstance(store_age, (int, float)) or store_age < 0:
            return False

    return True


def is_direct_competitor(competitor, reference_category, reference_price):
    """
    Determine if a competitor is a direct competitor.
    Direct = same product category AND price within ±30% of reference.
    """
    comp_category = competitor.get("product_category", "").lower().strip()
    ref_category = reference_category.lower().strip()

    if comp_category != ref_category:
        return False

    comp_price = competitor.get("price", 0)
    lower_bound = reference_price * (1 - PRICE_RANGE_TOLERANCE)
    upper_bound = reference_price * (1 + PRICE_RANGE_TOLERANCE)

    return lower_bound <= comp_price <= upper_bound


def is_indirect_competitor(competitor, reference_category, reference_keywords):
    """
    Determine if a competitor is indirect — adjacent category or partial
    keyword overlap but not a direct match.
    """
    comp_category = competitor.get("product_category", "").lower().strip()
    ref_category = reference_category.lower().strip()

    # Same category but outside price range counts as indirect.
    if comp_category == ref_category:
        return True

    comp_keywords = set(
        kw.lower().strip() for kw in competitor.get("keywords", [])
    )
    ref_keywords = set(kw.lower().strip() for kw in reference_keywords)

    if not ref_keywords or not comp_keywords:
        return False

    overlap = comp_keywords & ref_keywords
    overlap_ratio = len(overlap) / len(ref_keywords) if ref_keywords else 0

    return overlap_ratio >= 0.3


def get_price_bounds(reference_price, tolerance=None):
    """Return (lower, upper) price bounds for competitor matching."""
    tol = tolerance if tolerance is not None else PRICE_RANGE_TOLERANCE
    lower = reference_price * (1 - tol)
    upper = reference_price * (1 + tol)
    return round(lower, 2), round(upper, 2)


def is_within_analysis_limits(competitor_count):
    """Check whether the competitor count is within processing limits."""
    return MIN_COMPETITORS_FOR_ANALYSIS <= competitor_count <= MAX_COMPETITORS_ANALYZED
