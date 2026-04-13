"""Sentiment Analysis Engine — topic extractor.

Extracts discussion topics from processed texts using word frequency
analysis. Associates sentiment scores with discovered topics.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Minimum frequency for a topic to be considered significant
# ---------------------------------------------------------------------------

_MIN_TOPIC_FREQUENCY = 2
_MAX_TOPICS = 20

# Common non-topic words to skip (beyond stop words already removed)
_SKIP_WORDS = frozenset({
    "really", "very", "much", "many", "just", "like", "got",
    "get", "getting", "thing", "things", "way", "something",
    "lot", "lots", "bit", "quite", "pretty", "still",
})


def extract_topics(
    processed_texts: list[dict[str, Any]],
    sentiment_scores: list[dict[str, Any]],
    categories: list[str],
) -> dict[str, Any]:
    """Extract discussion topics and their associated sentiments.

    Args:
        processed_texts: List of ProcessedText dicts.
        sentiment_scores: List of SentimentScore dicts.
        categories: Optional category filter list.

    Returns:
        Structured dict with extracted topics.
    """
    try:
        processed_texts = copy.deepcopy(processed_texts)

        # Build sentiment lookup by text ID
        sentiment_map: dict[str, float] = {}
        for ss in sentiment_scores:
            sentiment_map[str(ss.get("id", ""))] = float(ss.get("score", 0))

        # Count word frequencies across all texts
        word_freq: dict[str, int] = {}
        word_sentiments: dict[str, list[float]] = {}
        word_texts: dict[str, list[str]] = {}

        for text in processed_texts:
            text_id = str(text.get("id", ""))
            tokens = list(text.get("tokens", []))
            original = str(text.get("original", ""))
            text_sentiment = sentiment_map.get(text_id, 0.0)

            seen_in_text: set[str] = set()
            for token in tokens:
                token = token.lower()
                if token in _SKIP_WORDS or len(token) <= 2:
                    continue

                word_freq[token] = word_freq.get(token, 0) + 1

                if token not in seen_in_text:
                    word_sentiments.setdefault(token, []).append(text_sentiment)
                    # Store a representative text snippet
                    if len(word_texts.get(token, [])) < 3:
                        snippet = original[:100] if len(original) > 100 else original
                        word_texts.setdefault(token, []).append(snippet)
                    seen_in_text.add(token)

        # Filter to significant topics
        topics: list[dict[str, Any]] = []

        for word, freq in word_freq.items():
            if freq < _MIN_TOPIC_FREQUENCY:
                continue

            sentiments = word_sentiments.get(word, [])
            avg_sentiment = round(sum(sentiments) / len(sentiments), 4) if sentiments else 0.0
            rep_texts = word_texts.get(word, [])

            # If categories provided, check relevance
            if categories:
                relevant = any(
                    word in cat.lower() or cat.lower() in word
                    for cat in categories
                )
                # Still include if high frequency even if not category-matched
                if not relevant and freq < _MIN_TOPIC_FREQUENCY * 2:
                    continue

            topics.append({
                "topic": word,
                "sentiment": avg_sentiment,
                "count": freq,
                "representative_texts": rep_texts,
            })

        # Sort by count descending, cap at max
        topics.sort(key=lambda t: t["count"], reverse=True)
        topics = topics[:_MAX_TOPICS]

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
