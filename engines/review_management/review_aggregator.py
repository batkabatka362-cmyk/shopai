"""Review Management Engine — review aggregator.

Aggregates raw reviews into summary statistics: total count, average rating,
rating distribution (1-5 star buckets), verified vs unverified split,
and average helpful-vote count.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def aggregate_reviews(
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate review data into summary statistics.

    Args:
        reviews: List of ReviewItem dicts.

    Returns:
        Structured dict with ReviewSummary data.
    """
    try:
        items = copy.deepcopy(reviews)

        if not items:
            return {
                "status": "success",
                "summary": {
                    "avg_rating": 0.0,
                    "total_reviews": 0,
                    "rating_distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
                    "verified_count": 0,
                    "unverified_count": 0,
                    "avg_helpful_votes": 0.0,
                },
            }

        total = len(items)

        # Rating distribution
        distribution: dict[str, int] = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
        rating_sum = 0.0
        verified_count = 0
        helpful_sum = 0

        for review in items:
            rating = float(review.get("rating", 0))
            rating_sum += rating

            # Bucket into 1-5 stars (clamp)
            bucket = max(1, min(5, round(rating)))
            distribution[str(bucket)] += 1

            if review.get("verified", False):
                verified_count += 1

            helpful_sum += int(review.get("helpful_votes", 0))

        avg_rating = round(rating_sum / total, 2)
        avg_helpful = round(helpful_sum / total, 2)

        return {
            "status": "success",
            "summary": {
                "avg_rating": avg_rating,
                "total_reviews": total,
                "rating_distribution": distribution,
                "verified_count": verified_count,
                "unverified_count": total - verified_count,
                "avg_helpful_votes": avg_helpful,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "summary": {},
            "error": f"Review aggregation failed: {exc}",
        }
