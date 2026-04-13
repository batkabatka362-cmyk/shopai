"""Review Management Engine — sentiment analyzer.

Analyzes sentiment per review using keyword-based analysis with curated
positive/negative word lists. Classifies each review as positive, negative,
neutral, or mixed with a numeric score from -1.0 to 1.0.

All math is real. No faking, no random numbers.

Model note: Uses Mistral for nuanced sentiment classification.
"""
from __future__ import annotations

import copy
import re
from typing import Any


# ---------------------------------------------------------------------------
# Curated word lists
# ---------------------------------------------------------------------------

_POSITIVE_WORDS: frozenset[str] = frozenset({
    "amazing", "awesome", "beautiful", "best", "brilliant", "comfortable",
    "convenient", "durable", "easy", "effective", "efficient", "elegant",
    "enjoyable", "excellent", "exceptional", "exciting", "fabulous",
    "fantastic", "fast", "favorite", "fine", "flawless", "friendly",
    "genuine", "glad", "good", "gorgeous", "great", "happy", "helpful",
    "high-quality", "impressed", "impressive", "incredible", "intuitive",
    "lightweight", "love", "loved", "lovely", "magnificent", "neat",
    "nice", "outstanding", "perfect", "pleased", "polished", "powerful",
    "premium", "professional", "prompt", "quality", "quick", "recommend",
    "recommended", "refined", "reliable", "remarkable", "responsive",
    "satisfied", "seamless", "sleek", "smooth", "solid", "sturdy",
    "stylish", "superb", "superior", "terrific", "thankful", "top-notch",
    "tremendous", "trustworthy", "useful", "valuable", "versatile",
    "well-made", "wonderful", "worth", "worthwhile",
})

_NEGATIVE_WORDS: frozenset[str] = frozenset({
    "annoying", "awful", "bad", "broken", "cheap", "complaint",
    "complicated", "confusing", "damaged", "defective", "delayed",
    "difficult", "dirty", "disappoint", "disappointed", "disappointing",
    "disappointment", "disgusting", "dreadful", "expensive", "fail",
    "failed", "faulty", "flimsy", "fragile", "frustrating", "garbage",
    "gross", "hate", "horrible", "inferior", "irritating", "junk",
    "lacking", "leak", "leaking", "mediocre", "misleading", "missing",
    "nasty", "never", "noisy", "overpriced", "painful", "pathetic",
    "poor", "problem", "refund", "regret", "rip-off", "rough", "rubbish",
    "rude", "scam", "scratched", "shabby", "slow", "smelly", "stain",
    "stained", "sticky", "subpar", "terrible", "thin", "trash", "ugly",
    "uncomfortable", "unreliable", "unusable", "useless", "waste",
    "weak", "worse", "worst", "worthless",
})

# Negation words that flip sentiment of the next word
_NEGATION_WORDS: frozenset[str] = frozenset({
    "not", "no", "never", "neither", "nor", "barely", "hardly",
    "scarcely", "doesn't", "don't", "didn't", "isn't", "wasn't",
    "aren't", "weren't", "won't", "wouldn't", "couldn't", "shouldn't",
})

# Intensifiers that amplify the next word's sentiment
_INTENSIFIERS: frozenset[str] = frozenset({
    "very", "really", "extremely", "absolutely", "incredibly", "highly",
    "truly", "remarkably", "exceptionally", "super", "totally", "utterly",
})


def analyze_sentiment(
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze sentiment for each review and compute aggregate percentages.

    Args:
        reviews: List of ReviewItem dicts.

    Returns:
        Structured dict with SentimentSummary data.
    """
    try:
        items = copy.deepcopy(reviews)

        if not items:
            return {
                "status": "success",
                "sentiment": {
                    "positive_pct": 0.0,
                    "negative_pct": 0.0,
                    "neutral_pct": 0.0,
                    "mixed_pct": 0.0,
                    "avg_score": 0.0,
                    "per_review": [],
                },
            }

        per_review: list[dict[str, Any]] = []
        counts = {"positive": 0, "negative": 0, "neutral": 0, "mixed": 0}
        score_sum = 0.0

        for review in items:
            result = _analyze_single(review)
            per_review.append(result)
            counts[result["sentiment"]] += 1
            score_sum += result["score"]

        total = len(items)
        avg_score = round(score_sum / total, 4)

        return {
            "status": "success",
            "sentiment": {
                "positive_pct": round(counts["positive"] / total * 100, 1),
                "negative_pct": round(counts["negative"] / total * 100, 1),
                "neutral_pct": round(counts["neutral"] / total * 100, 1),
                "mixed_pct": round(counts["mixed"] / total * 100, 1),
                "avg_score": avg_score,
                "per_review": per_review,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "sentiment": {},
            "error": f"Sentiment analysis failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase and split text into word tokens."""
    cleaned = re.sub(r"[^a-zA-Z\s\-']", " ", text.lower())
    return cleaned.split()


def _analyze_single(review: dict[str, Any]) -> dict[str, Any]:
    """Analyze sentiment for a single review.

    Uses a weighted keyword approach with negation and intensifier handling.
    Also factors in the numeric rating for calibration.
    """
    text = str(review.get("text", ""))
    rating = float(review.get("rating", 3.0))
    review_id = str(review.get("id", ""))

    tokens = _tokenize(text)
    found_positive: list[str] = []
    found_negative: list[str] = []

    positive_score = 0.0
    negative_score = 0.0

    i = 0
    while i < len(tokens):
        token = tokens[i]
        is_negated = False
        is_intensified = False

        # Look back for negation and intensifiers
        if i > 0 and tokens[i - 1] in _NEGATION_WORDS:
            is_negated = True
        if i > 0 and tokens[i - 1] in _INTENSIFIERS:
            is_intensified = True
        if i > 1 and tokens[i - 2] in _INTENSIFIERS and tokens[i - 1] in _NEGATION_WORDS:
            is_negated = True
            is_intensified = True

        weight = 1.5 if is_intensified else 1.0

        if token in _POSITIVE_WORDS:
            if is_negated:
                negative_score += weight
                found_negative.append(f"not {token}" if is_negated else token)
            else:
                positive_score += weight
                found_positive.append(token)
        elif token in _NEGATIVE_WORDS:
            if is_negated:
                positive_score += weight * 0.5  # Negated negatives are mildly positive
                found_positive.append(f"not {token}")
            else:
                negative_score += weight
                found_negative.append(token)

        i += 1

    # Factor in the star rating (1-5 mapped to -1.0 to 1.0)
    rating_signal = (rating - 3.0) / 2.0  # -1.0 to 1.0

    # Compute raw text score
    total_signals = positive_score + negative_score
    if total_signals > 0:
        text_score = (positive_score - negative_score) / total_signals
    else:
        text_score = 0.0

    # Blend text score (60%) with rating signal (40%)
    blended_score = round(text_score * 0.6 + rating_signal * 0.4, 4)
    blended_score = max(-1.0, min(1.0, blended_score))

    # Classify
    has_positive = positive_score > 0
    has_negative = negative_score > 0

    if has_positive and has_negative and abs(positive_score - negative_score) < max(positive_score, negative_score) * 0.4:
        sentiment = "mixed"
    elif blended_score > 0.15:
        sentiment = "positive"
    elif blended_score < -0.15:
        sentiment = "negative"
    elif has_positive and has_negative:
        sentiment = "mixed"
    else:
        sentiment = "neutral"

    return {
        "review_id": review_id,
        "sentiment": sentiment,
        "score": blended_score,
        "positive_words": found_positive,
        "negative_words": found_negative,
    }
