"""Sentiment Analysis Engine — sentiment scorer.

Scores text sentiment from -1.0 (negative) to +1.0 (positive)
using a keyword lexicon approach. Handles negation, intensifiers,
and computes per-text and aggregate sentiment.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Sentiment lexicon
# ---------------------------------------------------------------------------

_POSITIVE_WORDS = {
    "great": 0.8, "excellent": 0.9, "amazing": 0.9, "awesome": 0.85,
    "love": 0.85, "loved": 0.85, "wonderful": 0.9, "fantastic": 0.9,
    "perfect": 0.95, "good": 0.6, "nice": 0.5, "happy": 0.7,
    "pleased": 0.7, "satisfied": 0.7, "recommend": 0.75, "best": 0.8,
    "beautiful": 0.8, "impressive": 0.8, "outstanding": 0.9,
    "helpful": 0.7, "easy": 0.5, "fast": 0.6, "quality": 0.65,
    "reliable": 0.7, "comfortable": 0.6, "enjoy": 0.7, "enjoyed": 0.7,
    "delighted": 0.85, "superb": 0.9, "exceptional": 0.9,
    "smooth": 0.5, "friendly": 0.6, "professional": 0.6,
    "worth": 0.5, "thanks": 0.5, "thank": 0.5, "appreciate": 0.7,
}

_NEGATIVE_WORDS = {
    "bad": -0.6, "terrible": -0.9, "horrible": -0.9, "awful": -0.85,
    "worst": -0.9, "poor": -0.7, "disappointing": -0.8, "disappointed": -0.8,
    "broken": -0.7, "defective": -0.8, "useless": -0.8, "hate": -0.85,
    "hated": -0.85, "waste": -0.7, "slow": -0.5, "difficult": -0.5,
    "ugly": -0.6, "cheap": -0.4, "overpriced": -0.7, "frustrating": -0.75,
    "annoying": -0.6, "problem": -0.5, "issue": -0.4, "bug": -0.5,
    "error": -0.5, "fail": -0.7, "failed": -0.7, "refund": -0.6,
    "return": -0.3, "complaint": -0.6, "rude": -0.7, "unhelpful": -0.6,
    "unresponsive": -0.6, "damaged": -0.7, "missing": -0.5, "wrong": -0.6,
    "never": -0.3, "worse": -0.7, "scam": -0.9, "fraud": -0.9,
}

# Negation words that flip sentiment
_NEGATORS = {"not", "no", "never", "neither", "nobody", "nothing",
             "nowhere", "nor", "cannot", "can't", "don't", "doesn't",
             "didn't", "won't", "wouldn't", "shouldn't", "couldn't",
             "isn't", "aren't", "wasn't", "weren't"}

# Intensifiers that amplify sentiment
_INTENSIFIERS = {"very": 1.3, "really": 1.3, "extremely": 1.5,
                 "absolutely": 1.5, "totally": 1.4, "completely": 1.4,
                 "incredibly": 1.5, "highly": 1.3, "quite": 1.2}


def score_sentiments(
    processed_texts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score sentiment for each processed text.

    Args:
        processed_texts: List of ProcessedText dicts from text_preprocessor.

    Returns:
        Structured dict with sentiment scores and distribution.
    """
    try:
        processed_texts = copy.deepcopy(processed_texts)
        scores: list[dict[str, Any]] = []

        positive_count = 0
        neutral_count = 0
        negative_count = 0
        total_sentiment = 0.0

        for text in processed_texts:
            text_id = str(text.get("id", ""))
            tokens = list(text.get("tokens", []))

            score, pos_words, neg_words, confidence = _score_tokens(tokens)

            # Classify
            if score > 0.1:
                label = "positive"
                positive_count += 1
            elif score < -0.1:
                label = "negative"
                negative_count += 1
            else:
                label = "neutral"
                neutral_count += 1

            total_sentiment += score

            scores.append({
                "id": text_id,
                "score": round(score, 4),
                "label": label,
                "confidence": round(confidence, 4),
                "positive_words": pos_words,
                "negative_words": neg_words,
            })

        total = len(scores)
        overall = round(total_sentiment / total, 4) if total > 0 else 0.0

        distribution = {
            "positive": positive_count,
            "neutral": neutral_count,
            "negative": negative_count,
            "positive_pct": round(positive_count / total * 100, 2) if total > 0 else 0.0,
            "neutral_pct": round(neutral_count / total * 100, 2) if total > 0 else 0.0,
            "negative_pct": round(negative_count / total * 100, 2) if total > 0 else 0.0,
        }

        return {
            "status": "success",
            "sentiment_scores": scores,
            "overall_sentiment": overall,
            "sentiment_distribution": distribution,
        }
    except Exception as exc:
        return {
            "status": "error",
            "sentiment_scores": [],
            "error": f"Sentiment scoring failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_tokens(
    tokens: list[str],
) -> tuple[float, list[str], list[str], float]:
    """Score a list of tokens for sentiment.

    Returns:
        Tuple of (score, positive_words, negative_words, confidence).
    """
    if not tokens:
        return 0.0, [], [], 0.0

    total_score = 0.0
    scored_count = 0
    pos_words: list[str] = []
    neg_words: list[str] = []

    i = 0
    while i < len(tokens):
        token = tokens[i].lower()

        # Check for intensifier
        intensifier = _INTENSIFIERS.get(token, 1.0)
        if intensifier != 1.0 and i + 1 < len(tokens):
            i += 1
            token = tokens[i].lower()
        else:
            intensifier = 1.0

        # Check for negation in previous word
        is_negated = False
        if i > 0 and tokens[i - 1].lower() in _NEGATORS:
            is_negated = True

        # Score the token
        if token in _POSITIVE_WORDS:
            word_score = _POSITIVE_WORDS[token] * intensifier
            if is_negated:
                word_score = -word_score * 0.5
                neg_words.append(f"not {token}")
            else:
                pos_words.append(token)
            total_score += word_score
            scored_count += 1

        elif token in _NEGATIVE_WORDS:
            word_score = _NEGATIVE_WORDS[token] * intensifier
            if is_negated:
                word_score = -word_score * 0.5
                pos_words.append(f"not {token}")
            else:
                neg_words.append(token)
            total_score += word_score
            scored_count += 1

        i += 1

    # Normalize to [-1, 1]
    if scored_count > 0:
        normalized = total_score / scored_count
        normalized = max(-1.0, min(1.0, normalized))
    else:
        normalized = 0.0

    # Confidence based on how many sentiment words were found
    token_count = len(tokens)
    if token_count > 0:
        sentiment_density = scored_count / token_count
        confidence = min(sentiment_density * 5, 1.0)  # Scale up
    else:
        confidence = 0.0

    return normalized, pos_words, neg_words, confidence
