"""Feedback Processing Engine — priority scorer.

Scores each categorized feedback item for priority and urgency based on
sentiment intensity, category importance, and frequency signals.
"""
from __future__ import annotations

import copy
from typing import Any


_CATEGORY_WEIGHTS: dict[str, float] = {
    "product_quality": 0.9,
    "shipping": 0.7,
    "customer_service": 0.8,
    "pricing": 0.6,
    "usability": 0.5,
    "feature_request": 0.4,
    "other": 0.3,
}


def score_priorities(
    categorized: list[dict[str, Any]],
    feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score priority and urgency for each categorized feedback item.

    Args:
        categorized: Output from categorizer.
        feedback: Original feedback items (for sentiment data).

    Returns:
        Structured dict with prioritized feedback.
    """
    try:
        items = copy.deepcopy(categorized)
        sentiment_map: dict[str, float] = {}
        for fb in feedback:
            sentiment_map[str(fb.get("id", ""))] = float(fb.get("sentiment", 0.0))

        priorities: list[dict[str, Any]] = []

        for item in items:
            fid = str(item.get("id", ""))
            category = str(item.get("category", "other"))
            sentiment = sentiment_map.get(fid, 0.0)

            cat_weight = _CATEGORY_WEIGHTS.get(category, 0.3)
            sentiment_intensity = abs(sentiment)

            # Priority = category importance * sentiment intensity
            # Negative sentiment gets a boost (complaints are more urgent)
            negativity_boost = 0.2 if sentiment < -0.3 else 0.0
            score = round(
                cat_weight * 0.5 + sentiment_intensity * 0.3 + negativity_boost + item.get("confidence", 0.5) * 0.2,
                3,
            )
            score = round(min(score, 1.0), 3)

            urgency = _classify_urgency(score)
            impact = _classify_impact(cat_weight, sentiment_intensity)

            priorities.append({
                "id": fid,
                "category": category,
                "priority_score": score,
                "urgency": urgency,
                "impact": impact,
            })

        priorities.sort(key=lambda x: x["priority_score"], reverse=True)

        return {
            "status": "success",
            "priorities": priorities,
        }
    except Exception as exc:
        return {
            "status": "error",
            "priorities": [],
            "error": f"Priority scoring failed: {exc}",
        }


def _classify_urgency(score: float) -> str:
    """Classify urgency level from priority score."""
    if score >= 0.8:
        return "critical"
    if score >= 0.6:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _classify_impact(cat_weight: float, sentiment_intensity: float) -> str:
    """Classify expected impact."""
    combined = cat_weight * 0.6 + sentiment_intensity * 0.4
    if combined >= 0.7:
        return "high"
    if combined >= 0.4:
        return "medium"
    return "low"
