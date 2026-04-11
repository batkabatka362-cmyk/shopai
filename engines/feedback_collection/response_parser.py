"""Feedback Collection Engine — response parser.

Parses and structures raw feedback responses: extracts ratings,
sentiment indicators, themes, and structured data from text.
"""
from __future__ import annotations

import copy
from typing import Any


_POSITIVE_WORDS = {"great", "excellent", "love", "amazing", "perfect", "awesome", "good", "best", "happy", "wonderful"}
_NEGATIVE_WORDS = {"bad", "terrible", "awful", "worst", "hate", "poor", "disappointing", "broken", "slow", "horrible"}


def parse_responses(
    feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    """Parse and structure feedback responses.

    Args:
        feedback: Aggregated feedback from channels.

    Returns:
        Structured dict with parsed responses and sentiment.
    """
    try:
        data = copy.deepcopy(feedback)

        positive = 0
        negative = 0
        neutral = 0
        total_rating = 0.0
        rating_count = 0
        themes: dict[str, int] = {}

        for source_fb in data:
            responses = source_fb.get("responses", [])

            for resp in responses:
                # Extract rating
                rating = resp.get("rating", resp.get("score", resp.get("nps")))
                if rating is not None:
                    try:
                        r = float(rating)
                        total_rating += r
                        rating_count += 1
                    except (ValueError, TypeError):
                        pass

                # Sentiment from text
                text = str(resp.get("text", resp.get("comment", resp.get("message", "")))).lower()
                if text:
                    pos_count = sum(1 for w in _POSITIVE_WORDS if w in text)
                    neg_count = sum(1 for w in _NEGATIVE_WORDS if w in text)

                    if pos_count > neg_count:
                        positive += 1
                    elif neg_count > pos_count:
                        negative += 1
                    else:
                        neutral += 1

                    # Theme extraction (simple keyword matching)
                    theme_keywords = {
                        "shipping": ["shipping", "delivery", "shipped"],
                        "quality": ["quality", "durable", "broken", "defective"],
                        "price": ["price", "expensive", "cheap", "value", "cost"],
                        "service": ["service", "support", "help", "staff"],
                        "product": ["product", "item", "purchase"],
                    }
                    for theme, keywords in theme_keywords.items():
                        if any(kw in text for kw in keywords):
                            themes[theme] = themes.get(theme, 0) + 1

        total_sentiments = positive + negative + neutral
        avg_rating = round(total_rating / rating_count, 2) if rating_count > 0 else 0.0

        sentiment_summary: dict[str, Any] = {
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "positive_pct": round(positive / total_sentiments * 100, 1) if total_sentiments > 0 else 0.0,
            "negative_pct": round(negative / total_sentiments * 100, 1) if total_sentiments > 0 else 0.0,
            "avg_rating": avg_rating,
            "themes": themes,
        }

        return {
            "status": "success",
            "sentiment_summary": sentiment_summary,
            "total_parsed": total_sentiments,
        }
    except Exception as exc:
        return {
            "status": "error",
            "sentiment_summary": {},
            "error": f"Response parsing failed: {exc}",
        }
