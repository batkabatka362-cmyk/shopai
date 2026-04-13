"""Brand Perception Engine — sentiment aggregator.

Aggregates sentiment from mentions, reviews, and social posts
using keyword-based sentiment analysis.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Sentiment keyword lists
# ---------------------------------------------------------------------------

_POSITIVE_WORDS = {
    "love", "great", "excellent", "amazing", "awesome", "fantastic", "perfect",
    "wonderful", "outstanding", "brilliant", "superb", "delighted", "impressed",
    "recommend", "best", "happy", "pleased", "quality", "reliable", "beautiful",
    "enjoy", "satisfied", "exceptional", "favorite", "incredible", "premium",
    "fast", "easy", "helpful", "friendly", "professional", "clean", "fresh",
}

_NEGATIVE_WORDS = {
    "bad", "terrible", "horrible", "awful", "worst", "poor", "disappointed",
    "broken", "defective", "slow", "rude", "expensive", "overpriced", "waste",
    "scam", "fraud", "fake", "cheap", "flimsy", "unreliable", "difficult",
    "frustrating", "annoying", "useless", "complaint", "refund", "return",
    "damaged", "missing", "late", "delayed", "terrible", "hate", "ugly",
}

_THEME_KEYWORDS: dict[str, list[str]] = {
    "product quality": ["quality", "durable", "well-made", "premium", "craftsmanship"],
    "customer service": ["service", "support", "helpful", "responsive", "rude"],
    "shipping": ["shipping", "delivery", "fast", "slow", "late", "delayed"],
    "price value": ["price", "value", "expensive", "affordable", "overpriced", "worth"],
    "user experience": ["easy", "intuitive", "confusing", "simple", "difficult"],
}


def aggregate_sentiment(
    mentions: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    social_posts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate sentiment across all text sources.

    Args:
        mentions: List of mention dicts.
        reviews: List of review dicts.
        social_posts: List of social post dicts.

    Returns:
        Structured dict with sentiment aggregation.
    """
    try:
        # Collect all texts
        all_texts: list[str] = []
        for m in mentions:
            all_texts.append(str(m.get("text", "")))
        for r in reviews:
            all_texts.append(str(r.get("text", r.get("body", ""))))
        for p in social_posts:
            all_texts.append(str(p.get("text", p.get("content", ""))))

        if not all_texts:
            return {
                "status": "success",
                "sentiment": {
                    "positive_pct": 0.0,
                    "negative_pct": 0.0,
                    "neutral_pct": 100.0,
                    "avg_sentiment_score": 0.0,
                    "top_positive_themes": [],
                    "top_negative_themes": [],
                },
            }

        positive_count = 0
        negative_count = 0
        neutral_count = 0
        sentiment_scores: list[float] = []
        theme_positive: dict[str, int] = {}
        theme_negative: dict[str, int] = {}

        for text in all_texts:
            words = set(w.lower().strip(".,!?;:\"'()") for w in text.split())
            pos_hits = len(words & _POSITIVE_WORDS)
            neg_hits = len(words & _NEGATIVE_WORDS)

            if pos_hits > neg_hits:
                positive_count += 1
                score = min(pos_hits / max(len(words), 1) * 10, 1.0)
                sentiment_scores.append(score)
            elif neg_hits > pos_hits:
                negative_count += 1
                score = -min(neg_hits / max(len(words), 1) * 10, 1.0)
                sentiment_scores.append(score)
            else:
                neutral_count += 1
                sentiment_scores.append(0.0)

            # Theme detection
            text_lower = text.lower()
            for theme, keywords in _THEME_KEYWORDS.items():
                for kw in keywords:
                    if kw in text_lower:
                        if pos_hits > neg_hits:
                            theme_positive[theme] = theme_positive.get(theme, 0) + 1
                        elif neg_hits > pos_hits:
                            theme_negative[theme] = theme_negative.get(theme, 0) + 1
                        break

        total = len(all_texts)
        positive_pct = round(positive_count / total * 100, 1)
        negative_pct = round(negative_count / total * 100, 1)
        neutral_pct = round(neutral_count / total * 100, 1)
        avg_score = round(sum(sentiment_scores) / len(sentiment_scores), 2)

        top_pos = sorted(theme_positive, key=lambda k: theme_positive[k], reverse=True)[:3]
        top_neg = sorted(theme_negative, key=lambda k: theme_negative[k], reverse=True)[:3]

        return {
            "status": "success",
            "sentiment": {
                "positive_pct": positive_pct,
                "negative_pct": negative_pct,
                "neutral_pct": neutral_pct,
                "avg_sentiment_score": avg_score,
                "top_positive_themes": top_pos,
                "top_negative_themes": top_neg,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "sentiment": {},
            "error": f"Sentiment aggregation failed: {exc}",
        }
