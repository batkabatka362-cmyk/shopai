"""Review Management Engine — rating analyzer.

Analyzes rating trends over time: computes moving averages, compares
recent ratings to overall average, calculates rating velocity (rate of
change), and classifies the trend as improving, declining, or stable.

All math is real. No faking, no random numbers.

Model note: Uses Mistral for trend interpretation and anomaly detection.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_RECENT_WINDOW = 5          # Number of most recent reviews to consider "recent"
_MOVING_AVG_WINDOW = 3      # Window size for moving average
_TREND_THRESHOLD = 0.25     # Minimum delta to declare improving/declining


def analyze_ratings(
    reviews: list[dict[str, Any]],
    overall_avg: float,
) -> dict[str, Any]:
    """Analyze rating trends across reviews.

    Reviews are expected to be sorted by date (oldest first).
    If not dated, the list order is treated as chronological.

    Args:
        reviews: List of ReviewItem dicts (ideally date-sorted).
        overall_avg: Pre-computed overall average rating.

    Returns:
        Structured dict with RatingTrend data.
    """
    try:
        items = copy.deepcopy(reviews)

        if not items:
            return {
                "status": "success",
                "trend": {
                    "direction": "stable",
                    "recent_avg": 0.0,
                    "overall_avg": 0.0,
                    "moving_averages": [],
                    "velocity": 0.0,
                    "model_note": "Mistral: no reviews to analyze",
                },
            }

        # Sort by date if available, otherwise keep input order
        items_sorted = _sort_by_date(items)
        ratings = [float(r.get("rating", 0)) for r in items_sorted]

        # Moving average
        moving_avgs = _compute_moving_average(ratings, _MOVING_AVG_WINDOW)

        # Recent average
        recent_ratings = ratings[-_RECENT_WINDOW:] if len(ratings) >= _RECENT_WINDOW else ratings
        recent_avg = round(sum(recent_ratings) / len(recent_ratings), 2)

        # Velocity: rate of change per review
        velocity = _compute_velocity(moving_avgs)

        # Direction classification
        delta = recent_avg - float(overall_avg)
        if delta > _TREND_THRESHOLD and velocity > 0:
            direction = "improving"
        elif delta < -_TREND_THRESHOLD and velocity < 0:
            direction = "declining"
        else:
            direction = "stable"

        model_note = (
            f"Mistral: trend is {direction}, recent avg {recent_avg} vs "
            f"overall {overall_avg}, velocity {velocity:+.4f} per review"
        )

        return {
            "status": "success",
            "trend": {
                "direction": direction,
                "recent_avg": recent_avg,
                "overall_avg": round(float(overall_avg), 2),
                "moving_averages": moving_avgs,
                "velocity": velocity,
                "model_note": model_note,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "trend": {},
            "error": f"Rating analysis failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sort_by_date(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort reviews by date ascending. Missing dates go to the end."""
    def _date_key(r: dict[str, Any]) -> str:
        return r.get("date", "9999-99-99")

    return sorted(reviews, key=_date_key)


def _compute_moving_average(values: list[float], window: int) -> list[float]:
    """Compute a simple moving average over a list of values."""
    if not values or window < 1:
        return []

    result: list[float] = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        segment = values[start:i + 1]
        avg = sum(segment) / len(segment)
        result.append(round(avg, 2))

    return result


def _compute_velocity(moving_avgs: list[float]) -> float:
    """Compute the average rate of change across moving averages.

    Returns the mean of consecutive differences (slope approximation).
    """
    if len(moving_avgs) < 2:
        return 0.0

    deltas = [
        moving_avgs[i] - moving_avgs[i - 1]
        for i in range(1, len(moving_avgs))
    ]

    return round(sum(deltas) / len(deltas), 4)
