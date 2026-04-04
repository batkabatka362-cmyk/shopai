"""Brand Perception Engine — mention tracker.

Tracks brand mentions across simulated channels, counting
mentions by source and extracting relevant text snippets.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def track_mentions(
    brand_name: str,
    mentions: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    social_posts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track brand mentions across all sources.

    Args:
        brand_name: The brand name to track.
        mentions: List of mention dicts with source, text, date.
        reviews: List of review dicts.
        social_posts: List of social post dicts.

    Returns:
        Structured dict with mention tracking results.
    """
    try:
        brand_lower = brand_name.lower()
        by_source: dict[str, int] = {}
        mention_texts: list[str] = []

        # Process explicit mentions
        for mention in mentions:
            source = str(mention.get("source", "unknown"))
            text = str(mention.get("text", ""))
            by_source[source] = by_source.get(source, 0) + 1
            if brand_lower in text.lower():
                mention_texts.append(text[:200])

        # Process reviews as mentions
        for review in reviews:
            text = str(review.get("text", review.get("body", "")))
            source = "reviews"
            by_source[source] = by_source.get(source, 0) + 1
            if brand_lower in text.lower():
                mention_texts.append(text[:200])

        # Process social posts as mentions
        for post in social_posts:
            text = str(post.get("text", post.get("content", "")))
            source = str(post.get("platform", "social"))
            by_source[source] = by_source.get(source, 0) + 1
            if brand_lower in text.lower():
                mention_texts.append(text[:200])

        total = sum(by_source.values())

        return {
            "status": "success",
            "tracking": {
                "total_mentions": total,
                "by_source": by_source,
                "mention_texts": mention_texts[:50],
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "tracking": {},
            "error": f"Mention tracking failed: {exc}",
        }
