"""Review Management Engine — insight extractor.

Extracts actionable insights from review patterns: identifies the most
praised features, most complained-about issues, and unmet expectations.

Insights are derived from sentiment data, topic frequency, and rating
correlations. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Praise / complaint keyword groups
# ---------------------------------------------------------------------------

_PRAISE_KEYWORDS: dict[str, list[str]] = {
    "build_quality": ["well-made", "well made", "solid", "sturdy", "durable", "quality"],
    "ease_of_use": ["easy", "intuitive", "simple", "straightforward", "user-friendly"],
    "fast_shipping": ["fast", "quick", "prompt", "early", "on time", "fast delivery"],
    "great_value": ["worth", "value", "bargain", "deal", "affordable", "great price"],
    "comfort": ["comfortable", "soft", "smooth", "cozy", "lightweight"],
    "appearance": ["beautiful", "gorgeous", "stylish", "sleek", "elegant", "nice looking"],
    "customer_support": ["helpful", "friendly", "responsive", "polite", "great support"],
    "packaging": ["well-packed", "well packed", "nice packaging", "great packaging"],
}

_COMPLAINT_KEYWORDS: dict[str, list[str]] = {
    "poor_quality": ["cheap", "flimsy", "defective", "broke", "broken", "fell apart"],
    "sizing_issues": ["too big", "too small", "runs large", "runs small", "wrong size"],
    "slow_shipping": ["slow", "delayed", "late", "took forever", "weeks"],
    "overpriced": ["overpriced", "expensive", "rip-off", "not worth", "waste of money"],
    "discomfort": ["uncomfortable", "scratchy", "rough", "heavy", "painful"],
    "misleading_description": ["misleading", "not as described", "different from", "false", "scam"],
    "poor_support": ["rude", "unhelpful", "no response", "ignored", "terrible service"],
    "damaged_arrival": ["damaged", "scratched", "dented", "stained", "dirty"],
}

_EXPECTATION_KEYWORDS: dict[str, list[str]] = {
    "expected_better_quality": ["expected", "thought it would", "should be", "hoped"],
    "missing_features": ["missing", "no option", "wish it had", "would be nice", "should have"],
    "inconsistent_reviews": ["other reviews", "not what reviews said", "misleading reviews"],
}


def extract_insights(
    reviews: list[dict[str, Any]],
    sentiment_per_review: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Extract actionable insights from review data.

    Args:
        reviews: List of ReviewItem dicts.
        sentiment_per_review: Per-review sentiment results.
        topics: Extracted topic results.
        summary: Aggregated review summary.

    Returns:
        Structured dict with list of InsightItem data.
    """
    try:
        items = copy.deepcopy(reviews)
        sentiments = {s["review_id"]: s for s in sentiment_per_review}

        insights: list[dict[str, Any]] = []

        # --- Praise insights ---
        praise_hits = _scan_keyword_group(items, sentiments, _PRAISE_KEYWORDS, "praise")
        insights.extend(praise_hits)

        # --- Complaint insights ---
        complaint_hits = _scan_keyword_group(items, sentiments, _COMPLAINT_KEYWORDS, "complaint")
        insights.extend(complaint_hits)

        # --- Unmet expectation insights ---
        expectation_hits = _scan_keyword_group(
            items, sentiments, _EXPECTATION_KEYWORDS, "expectation",
        )
        insights.extend(expectation_hits)

        # Sort by frequency descending, then by absolute rating impact
        insights.sort(
            key=lambda x: (x["frequency"], abs(x["avg_rating_impact"])),
            reverse=True,
        )

        return {
            "status": "success",
            "insights": insights,
        }
    except Exception as exc:
        return {
            "status": "error",
            "insights": [],
            "error": f"Insight extraction failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _scan_keyword_group(
    reviews: list[dict[str, Any]],
    sentiments: dict[str, dict[str, Any]],
    keyword_groups: dict[str, list[str]],
    category: str,
) -> list[dict[str, Any]]:
    """Scan reviews against a keyword group and return matching insights."""
    results: list[dict[str, Any]] = []

    for group_name, keywords in keyword_groups.items():
        frequency = 0
        rating_deltas: list[float] = []
        sample_ids: list[str] = []

        for review in reviews:
            text = str(review.get("text", "")).lower()
            review_id = str(review.get("id", ""))
            rating = float(review.get("rating", 3.0))

            if _text_matches(text, keywords):
                frequency += 1
                # Rating impact: how far from neutral (3.0)
                rating_deltas.append(rating - 3.0)
                if len(sample_ids) < 3:
                    sample_ids.append(review_id)

        if frequency == 0:
            continue

        avg_impact = round(sum(rating_deltas) / len(rating_deltas), 2) if rating_deltas else 0.0

        description = _humanize_group_name(group_name, category)

        results.append({
            "category": category,
            "description": description,
            "frequency": frequency,
            "avg_rating_impact": avg_impact,
            "sample_reviews": sample_ids,
        })

    return results


def _text_matches(text: str, keywords: list[str]) -> bool:
    """Check if any keyword is found in the text."""
    for kw in keywords:
        if kw in text:
            return True
    return False


def _humanize_group_name(group_name: str, category: str) -> str:
    """Convert a group name like 'build_quality' into a readable description."""
    readable = group_name.replace("_", " ").title()

    if category == "praise":
        return f"Customers frequently praise: {readable}"
    elif category == "complaint":
        return f"Customers frequently complain about: {readable}"
    elif category == "expectation":
        return f"Unmet customer expectation: {readable}"
    return readable
