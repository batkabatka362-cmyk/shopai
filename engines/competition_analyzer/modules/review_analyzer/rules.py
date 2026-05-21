"""
rules.py — Validation rules and authenticity checks for review analysis.

Constants:
    MIN_REVIEWS_FOR_ANALYSIS — minimum review count for reliable conclusions
    MAX_REVIEW_AGE_YEARS — discard reviews older than this
    HIGH_NEGATIVE_THRESHOLD — flag products with this % of 1-star reviews

Functions:
    validate_review_dataset(reviews) — ensure data meets minimum requirements
    check_review_authenticity(review) — evaluate a single review for fakeness
    flag_suspicious_patterns(reviews) — detect batch-level suspicious signals
"""

from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

MIN_REVIEWS_FOR_ANALYSIS = 20
MAX_REVIEW_AGE_YEARS = 2
HIGH_NEGATIVE_THRESHOLD = 30  # percent
MIN_REVIEW_LENGTH_CHARS = 15
BURST_WINDOW_DAYS = 3
BURST_THRESHOLD_COUNT = 10
SHORT_REVIEW_CEILING = 30  # characters — reviews shorter than this are suspect
GENERIC_PHRASE_LIMIT = 0.4  # if >40% of reviews match generic phrases, flag


# ---------------------------------------------------------------------------
# Dataset validation
# ---------------------------------------------------------------------------

def validate_review_dataset(reviews):
    """Check whether a review list meets minimum analysis requirements.

    Returns:
        dict with is_valid (bool), reason (str or None), warnings (list)
    """
    warnings = []

    if not reviews:
        return {"is_valid": False, "reason": "No reviews provided.", "warnings": []}

    if len(reviews) < MIN_REVIEWS_FOR_ANALYSIS:
        return {
            "is_valid": False,
            "reason": (
                f"Only {len(reviews)} reviews — need at least "
                f"{MIN_REVIEWS_FOR_ANALYSIS} for reliable analysis."
            ),
            "warnings": [],
        }

    cutoff = datetime.now() - timedelta(days=MAX_REVIEW_AGE_YEARS * 365)
    recent = []
    for r in reviews:
        date_val = r.get("date")
        if date_val:
            try:
                dt = datetime.fromisoformat(str(date_val))
                if dt >= cutoff:
                    recent.append(r)
                    continue
            except (ValueError, TypeError):
                # Unparseable date -- intentional fall-through
                # to ``recent.append(r)`` below so the review
                # still contributes to the count.
                pass
        # Keep reviews with no parseable date — they might still be useful.
        recent.append(r)

    if len(recent) < MIN_REVIEWS_FOR_ANALYSIS:
        return {
            "is_valid": False,
            "reason": (
                f"Only {len(recent)} reviews within the last {MAX_REVIEW_AGE_YEARS} years — "
                f"need at least {MIN_REVIEWS_FOR_ANALYSIS}."
            ),
            "warnings": [],
        }

    one_star_count = sum(1 for r in recent if r.get("rating") == 1)
    one_star_pct = one_star_count / len(recent) * 100
    if one_star_pct > HIGH_NEGATIVE_THRESHOLD:
        warnings.append(
            f"High 1-star rate: {one_star_pct:.1f}% of reviews are 1-star. "
            "Product may have fundamental issues."
        )

    missing_text = sum(1 for r in recent if not r.get("text"))
    if missing_text > len(recent) * 0.5:
        warnings.append("Over 50% of reviews have no text — sentiment analysis limited.")

    return {"is_valid": True, "reason": None, "warnings": warnings}


# ---------------------------------------------------------------------------
# Single-review authenticity
# ---------------------------------------------------------------------------

GENERIC_PHRASES = [
    "great product",
    "love it",
    "highly recommend",
    "five stars",
    "amazing product",
    "very good",
    "excellent product",
    "works great",
    "just as described",
    "fast delivery",
    "best purchase",
    "very happy",
    "perfect product",
    "good quality",
    "would buy again",
]


def check_review_authenticity(review):
    """Evaluate whether a single review looks authentic.

    Returns:
        dict with is_authentic (bool) and flags (list of reasons)
    """
    flags = []
    text = review.get("text", "")

    if len(text) < SHORT_REVIEW_CEILING:
        flags.append("very_short_text")

    text_lower = text.lower().strip()
    for phrase in GENERIC_PHRASES:
        if text_lower == phrase or text_lower.rstrip(".!") == phrase:
            flags.append("generic_phrase_only")
            break

    if review.get("rating") == 5 and len(text) < SHORT_REVIEW_CEILING:
        flags.append("five_star_no_detail")

    if not review.get("verified", True):
        flags.append("unverified_purchase")

    is_authentic = len(flags) < 2
    return {"is_authentic": is_authentic, "flags": flags}


# ---------------------------------------------------------------------------
# Batch-level suspicious patterns
# ---------------------------------------------------------------------------

def flag_suspicious_patterns(reviews):
    """Detect dataset-level patterns that suggest manipulation.

    Returns:
        list of warning strings
    """
    flags = []

    # Check for review bursts (many reviews in a short window)
    dates = []
    for r in reviews:
        d = r.get("date")
        if d:
            try:
                dates.append(datetime.fromisoformat(str(d)))
            except (ValueError, TypeError):
                continue

    dates.sort()
    for i in range(len(dates)):
        window_end = dates[i] + timedelta(days=BURST_WINDOW_DAYS)
        burst_count = sum(1 for d in dates[i:] if d <= window_end)
        if burst_count >= BURST_THRESHOLD_COUNT:
            flags.append(
                f"Review burst detected: {burst_count} reviews within "
                f"{BURST_WINDOW_DAYS} days around {dates[i].date()}."
            )
            break

    # Check for high proportion of generic short reviews
    total = max(len(reviews), 1)
    generic_count = 0
    for r in reviews:
        result = check_review_authenticity(r)
        if not result["is_authentic"]:
            generic_count += 1
    if generic_count / total > GENERIC_PHRASE_LIMIT:
        flags.append(
            f"High fake-review signal: {generic_count}/{total} reviews "
            "flagged as potentially inauthentic."
        )

    # Check for unnatural rating distribution (only 5-star and 1-star)
    ratings = [r.get("rating", 0) for r in reviews if r.get("rating")]
    if ratings:
        mid_ratings = sum(1 for rt in ratings if 2 <= rt <= 4)
        if mid_ratings / len(ratings) < 0.1 and len(ratings) >= MIN_REVIEWS_FOR_ANALYSIS:
            flags.append(
                "Polarized ratings: very few 2-4 star reviews — possible manipulation."
            )

    return flags
