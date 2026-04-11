"""
data.py — Reference benchmarks, keyword mappings, and indicator data.

Provides:
    CATEGORY_BENCHMARKS — avg rating and review count by product category
    VELOCITY_BENCHMARKS — typical review velocity per category
    COMPLAINT_KEYWORDS — keywords that map review text to complaint categories
    FAKE_REVIEW_INDICATORS — signals used to detect inauthentic reviews
"""


# ---------------------------------------------------------------------------
# Category benchmarks (avg rating, avg review count for top-50 listings)
# ---------------------------------------------------------------------------

CATEGORY_BENCHMARKS = {
    "electronics": {"avg_rating": 4.1, "avg_count": 850, "avg_velocity": 25},
    "clothing": {"avg_rating": 4.0, "avg_count": 320, "avg_velocity": 15},
    "beauty": {"avg_rating": 4.2, "avg_count": 600, "avg_velocity": 20},
    "home_kitchen": {"avg_rating": 4.3, "avg_count": 450, "avg_velocity": 12},
    "sports_outdoors": {"avg_rating": 4.2, "avg_count": 280, "avg_velocity": 10},
    "toys_games": {"avg_rating": 4.4, "avg_count": 520, "avg_velocity": 18},
    "health": {"avg_rating": 4.1, "avg_count": 700, "avg_velocity": 22},
    "pet_supplies": {"avg_rating": 4.3, "avg_count": 380, "avg_velocity": 14},
    "office_products": {"avg_rating": 4.2, "avg_count": 200, "avg_velocity": 8},
    "automotive": {"avg_rating": 4.1, "avg_count": 150, "avg_velocity": 6},
    "grocery": {"avg_rating": 4.3, "avg_count": 250, "avg_velocity": 12},
    "baby": {"avg_rating": 4.2, "avg_count": 340, "avg_velocity": 11},
    "tools": {"avg_rating": 4.3, "avg_count": 180, "avg_velocity": 7},
    "general": {"avg_rating": 4.1, "avg_count": 300, "avg_velocity": 12},
}


# ---------------------------------------------------------------------------
# Velocity benchmarks — what "good" looks like per tier
# ---------------------------------------------------------------------------

VELOCITY_BENCHMARKS = {
    "slow": {"reviews_per_month": 5, "label": "Niche or new product"},
    "moderate": {"reviews_per_month": 15, "label": "Established mid-tier seller"},
    "fast": {"reviews_per_month": 30, "label": "Category leader pace"},
    "viral": {"reviews_per_month": 60, "label": "Trending or viral product"},
}


def get_velocity_tier(reviews_per_month):
    """Classify a velocity value into a named tier."""
    if reviews_per_month >= 60:
        return "viral"
    if reviews_per_month >= 30:
        return "fast"
    if reviews_per_month >= 15:
        return "moderate"
    return "slow"


# ---------------------------------------------------------------------------
# Complaint category keywords
# ---------------------------------------------------------------------------

COMPLAINT_KEYWORDS = {
    "quality_issues": [
        "broke", "broken", "fell apart", "cheap", "flimsy", "defective",
        "poor quality", "stopped working", "cracked", "peeling", "faded",
        "thin material", "ripped", "tore", "malfunction", "doesn't last",
    ],
    "shipping_problems": [
        "late", "delayed", "never arrived", "lost in transit", "damaged box",
        "wrong item", "missing parts", "took forever", "slow shipping",
        "arrived damaged", "dented", "crushed", "shipping took",
    ],
    "sizing_fit": [
        "too small", "too big", "runs large", "runs small", "doesn't fit",
        "size chart wrong", "not true to size", "tight", "loose",
        "length is off", "width is wrong", "sizing issue",
    ],
    "not_as_described": [
        "not as pictured", "different color", "misleading", "false advertising",
        "doesn't match", "not what I expected", "looks nothing like",
        "description is wrong", "not as described", "fake", "counterfeit",
        "knockoff", "smaller than expected",
    ],
    "customer_service": [
        "no response", "terrible support", "won't refund", "rude",
        "unhelpful", "ignored", "no help", "customer service",
        "couldn't reach", "no reply",
    ],
    "packaging": [
        "no packaging", "poor packaging", "arrived open", "not sealed",
        "cheap packaging", "box was damaged", "unprotected",
    ],
}


def get_complaint_category(text):
    """Match review text to the most relevant complaint category.

    Returns the category name or 'other' if no keywords match.
    """
    text_lower = text.lower()
    best_category = "other"
    best_matches = 0

    for category, keywords in COMPLAINT_KEYWORDS.items():
        match_count = sum(1 for kw in keywords if kw in text_lower)
        if match_count > best_matches:
            best_matches = match_count
            best_category = category

    return best_category


# ---------------------------------------------------------------------------
# Benchmark lookup
# ---------------------------------------------------------------------------

def get_benchmark_for_category(category):
    """Return benchmarks for a category, falling back to 'general'."""
    return CATEGORY_BENCHMARKS.get(category, CATEGORY_BENCHMARKS["general"])


# ---------------------------------------------------------------------------
# Fake review indicators (used by rules.py)
# ---------------------------------------------------------------------------

FAKE_REVIEW_INDICATORS = {
    "text_signals": [
        "Very short review (under 30 chars) with 5-star rating",
        "Exact duplicate text across multiple reviews",
        "Only generic praise with no product-specific detail",
        "Excessive use of brand name or full product title in review",
        "Review text reads like marketing copy",
    ],
    "timing_signals": [
        "Cluster of reviews posted within 24-72 hours",
        "Reviews appearing before official product launch date",
        "Sudden spike after a long period of no reviews",
        "Most reviews posted on the same day of the week",
    ],
    "profile_signals": [
        "Reviewer has only ever left 5-star reviews",
        "Reviewer account created very recently",
        "Reviewer name follows a pattern (e.g., FirstnameLastinitial)",
        "Reviewer has reviewed competing products positively",
        "Unverified purchase on a high-value item",
    ],
    "statistical_signals": [
        "Rating distribution is bimodal (mostly 5-star and 1-star)",
        "Average rating is significantly above category average",
        "Review-to-purchase ratio is unusually high",
        "Photo review percentage is near zero despite high volume",
    ],
}


def get_all_fake_signals():
    """Return a flat list of all fake-review indicator strings."""
    signals = []
    for category_signals in FAKE_REVIEW_INDICATORS.values():
        signals.extend(category_signals)
    return signals
