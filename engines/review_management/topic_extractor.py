"""Review Management Engine — topic extractor.

Extracts topics mentioned across reviews. Recognizes seven core topic
categories: quality, shipping, price, packaging, customer_service,
size_fit, durability. Counts frequency and collects sample snippets.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import re
from typing import Any


# ---------------------------------------------------------------------------
# Topic keyword mappings
# ---------------------------------------------------------------------------

_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "quality": [
        "quality", "well-made", "well made", "craftsmanship", "build",
        "construction", "material", "materials", "premium", "finish",
        "finishing", "fabric", "texture", "stitching", "polish",
        "workmanship", "grade", "standard", "flawless", "defective",
        "faulty", "cheap", "flimsy",
    ],
    "shipping": [
        "shipping", "delivery", "arrived", "arrive", "package",
        "shipped", "transit", "tracking", "courier", "fedex", "ups",
        "usps", "dhl", "late", "delayed", "fast delivery",
        "slow delivery", "on time", "early", "days",
    ],
    "price": [
        "price", "pricing", "cost", "value", "money", "worth",
        "expensive", "cheap", "affordable", "overpriced", "bargain",
        "deal", "discount", "rip-off", "budget", "dollars", "paid",
    ],
    "packaging": [
        "packaging", "box", "wrapped", "wrapping", "unboxing",
        "bubble wrap", "protected", "damaged in transit",
        "gift wrap", "presentation", "cardboard",
    ],
    "customer_service": [
        "customer service", "support", "representative", "rep",
        "help desk", "response time", "refund", "return",
        "exchange", "warranty", "rude", "helpful", "friendly",
        "polite", "agent", "contacted", "email support", "chat",
    ],
    "size_fit": [
        "size", "sizing", "fit", "fitting", "too big", "too small",
        "runs large", "runs small", "true to size", "measurement",
        "dimensions", "length", "width", "height", "tight", "loose",
        "oversized", "undersized",
    ],
    "durability": [
        "durable", "durability", "lasting", "long-lasting", "broke",
        "broken", "tear", "tore", "worn", "wear", "sturdy",
        "fragile", "solid", "rugged", "lifespan", "months later",
        "year later", "fell apart", "holds up", "withstand",
    ],
}


def extract_topics(
    reviews: list[dict[str, Any]],
    sentiment_per_review: list[dict[str, Any]],
) -> dict[str, Any]:
    """Extract topics from reviews with frequency counts and sentiment.

    Args:
        reviews: List of ReviewItem dicts.
        sentiment_per_review: Per-review sentiment results.

    Returns:
        Structured dict with list of TopicResult data.
    """
    try:
        items = copy.deepcopy(reviews)
        sentiments = {s["review_id"]: s for s in sentiment_per_review}

        # Accumulate per topic
        topic_data: dict[str, dict[str, Any]] = {}
        for topic_name in _TOPIC_KEYWORDS:
            topic_data[topic_name] = {
                "frequency": 0,
                "sentiment_scores": [],
                "snippets": [],
            }

        for review in items:
            text = str(review.get("text", "")).lower()
            review_id = str(review.get("id", ""))
            review_sentiment = sentiments.get(review_id, {})
            sentiment_score = float(review_sentiment.get("score", 0.0))

            for topic_name, keywords in _TOPIC_KEYWORDS.items():
                matched = _match_topic(text, keywords)
                if matched:
                    td = topic_data[topic_name]
                    td["frequency"] += 1
                    td["sentiment_scores"].append(sentiment_score)
                    # Keep up to 3 sample snippets
                    if len(td["snippets"]) < 3:
                        snippet = _extract_snippet(text, matched)
                        td["snippets"].append(snippet)

        # Build sorted result (by frequency descending)
        topics: list[dict[str, Any]] = []
        for topic_name, td in topic_data.items():
            if td["frequency"] == 0:
                continue
            scores = td["sentiment_scores"]
            avg_sent = round(sum(scores) / len(scores), 4) if scores else 0.0
            topics.append({
                "topic": topic_name,
                "frequency": td["frequency"],
                "sentiment_avg": avg_sent,
                "sample_snippets": td["snippets"],
            })

        topics.sort(key=lambda t: t["frequency"], reverse=True)

        return {
            "status": "success",
            "topics": topics,
        }
    except Exception as exc:
        return {
            "status": "error",
            "topics": [],
            "error": f"Topic extraction failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _match_topic(text: str, keywords: list[str]) -> str | None:
    """Return the first keyword found in text, or None."""
    for kw in keywords:
        if kw in text:
            return kw
    return None


def _extract_snippet(text: str, keyword: str, context_chars: int = 60) -> str:
    """Extract a short snippet around the matched keyword."""
    idx = text.find(keyword)
    if idx == -1:
        return text[:120]

    start = max(0, idx - context_chars)
    end = min(len(text), idx + len(keyword) + context_chars)
    snippet = text[start:end].strip()

    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."

    return snippet
