"""Brand Perception Engine — reputation scorer.

Scores brand reputation 0-100 based on sentiment, mention volume,
and source diversity.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def score_reputation(
    tracking: dict[str, Any],
    sentiment: dict[str, Any],
) -> dict[str, Any]:
    """Score brand reputation based on tracking and sentiment data.

    Args:
        tracking: Mention tracking result dict.
        sentiment: Sentiment aggregation result dict.

    Returns:
        Structured dict with reputation score and factors.
    """
    try:
        total_mentions = int(tracking.get("total_mentions", 0))
        by_source = tracking.get("by_source", {})
        positive_pct = float(sentiment.get("positive_pct", 0.0))
        negative_pct = float(sentiment.get("negative_pct", 0.0))
        avg_score = float(sentiment.get("avg_sentiment_score", 0.0))

        # Factor 1: Sentiment balance (40% weight)
        # Higher positive ratio = higher score
        if positive_pct + negative_pct > 0:
            sentiment_factor = positive_pct / (positive_pct + negative_pct)
        else:
            sentiment_factor = 0.5
        sentiment_component = sentiment_factor * 100

        # Factor 2: Volume / visibility (30% weight)
        # More mentions = better visibility (logarithmic scale, cap at 100)
        if total_mentions > 0:
            import math
            volume_component = min(math.log(total_mentions + 1) * 20, 100)
        else:
            volume_component = 0.0

        # Factor 3: Source diversity (30% weight)
        # More diverse sources = more credible reputation
        source_count = len(by_source)
        diversity_component = min(source_count * 25, 100)

        # Weighted composite
        reputation_score = int(
            sentiment_component * 0.4
            + volume_component * 0.3
            + diversity_component * 0.3
        )
        reputation_score = max(0, min(100, reputation_score))

        factors = {
            "sentiment_component": round(sentiment_component, 1),
            "volume_component": round(volume_component, 1),
            "diversity_component": round(diversity_component, 1),
        }

        return {
            "status": "success",
            "reputation": {
                "reputation_score": reputation_score,
                "factors": factors,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "reputation": {},
            "error": f"Reputation scoring failed: {exc}",
        }
