"""Global Brain — scorer.

Scores knowledge items by reliability, recency, relevance, and impact.
Produces a composite score used for ranking and retrieval prioritization.

No connections to other modules — called only from flow.py.
"""
from __future__ import annotations

import time
from typing import Any


# Weight for each scoring dimension
_WEIGHTS = {
    "reliability": 0.30,
    "recency": 0.25,
    "relevance": 0.25,
    "impact": 0.20,
}


def score_knowledge(
    unique_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score each knowledge item on multiple dimensions.

    Dimensions:
        - reliability: based on confidence, source quality, and specificity
        - recency: based on timestamp freshness
        - relevance: based on category coverage and tag richness
        - impact: based on knowledge type and content indicators

    Args:
        unique_items: List of deduplicated StructuredKnowledge dicts.

    Returns:
        Structured dict with status and scored_items list.
    """
    try:
        if not unique_items:
            return {
                "status": "success",
                "scored_items": [],
                "error": None,
            }

        now = time.time()
        scored: list[dict[str, Any]] = []

        for item in unique_items:
            reliability = _score_reliability(item)
            recency = _score_recency(item, now)
            relevance = _score_relevance(item)
            impact = _score_impact(item)

            composite = (
                _WEIGHTS["reliability"] * reliability
                + _WEIGHTS["recency"] * recency
                + _WEIGHTS["relevance"] * relevance
                + _WEIGHTS["impact"] * impact
            )

            item_scored = dict(item)
            item_scored["score"] = round(composite, 4)
            item_scored["score_breakdown"] = {
                "reliability": round(reliability, 4),
                "recency": round(recency, 4),
                "relevance": round(relevance, 4),
                "impact": round(impact, 4),
            }
            scored.append(item_scored)

        # Sort by composite score descending
        scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        return {
            "status": "success",
            "scored_items": scored,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "scored_items": list(unique_items),
            "error": f"Scoring failed (items preserved): {exc}",
        }


# ---------------------------------------------------------------------------
# Scoring dimension functions
# ---------------------------------------------------------------------------

def _score_reliability(item: dict[str, Any]) -> float:
    """Score reliability based on confidence, specificity, and source.

    Higher confidence and numeric specificity increase reliability.
    """
    score = float(item.get("confidence", 0.5))

    content = item.get("content", "")
    # Numeric data is more reliable
    if any(ch.isdigit() for ch in content):
        score += 0.1
    # Percentage or multiplier references
    if "%" in content or "x " in content.lower():
        score += 0.05
    # Longer, more detailed content
    word_count = len(content.split())
    if word_count >= 10:
        score += 0.05
    if word_count >= 20:
        score += 0.05

    # Knowledge type affects reliability
    ktype = item.get("knowledge_type", "")
    if ktype == "fact":
        score += 0.1
    elif ktype == "correlation":
        score += 0.05
    elif ktype == "rule":
        score += 0.05

    return min(score, 1.0)


def _score_recency(item: dict[str, Any], now: float) -> float:
    """Score recency based on timestamp.

    Items from the current session get high recency. Older items decay.
    """
    timestamp_str = item.get("timestamp", "") or item.get("structured_at", "")
    if not timestamp_str:
        return 0.5  # unknown age, neutral score

    try:
        ts = time.mktime(time.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ"))
        age_hours = max((now - ts) / 3600.0, 0.0)
    except (ValueError, OverflowError):
        return 0.5

    # Exponential decay: half-life of 168 hours (1 week)
    half_life = 168.0
    decay = 0.5 ** (age_hours / half_life)
    return max(decay, 0.05)


def _score_relevance(item: dict[str, Any]) -> float:
    """Score relevance based on category and tag coverage.

    Items with specific categories and multiple tags score higher.
    """
    score = 0.4

    # Having a non-default category
    category = item.get("category", "")
    if category and category != "operational":
        score += 0.1

    # Having a specific subcategory
    subcategory = item.get("subcategory", "general")
    if subcategory != "general":
        score += 0.1

    # Tag richness
    tags = item.get("tags", [])
    tag_count = len(tags)
    if tag_count >= 2:
        score += 0.1
    if tag_count >= 4:
        score += 0.1
    if tag_count >= 6:
        score += 0.1

    return min(score, 1.0)


def _score_impact(item: dict[str, Any]) -> float:
    """Score potential impact of the knowledge item.

    Correlations and rules have higher impact. Content with action
    words or comparative language suggests actionable insights.
    """
    score = 0.3

    ktype = item.get("knowledge_type", "")
    if ktype == "correlation":
        score += 0.2
    elif ktype == "rule":
        score += 0.15
    elif ktype == "insight":
        score += 0.1

    content = item.get("content", "").lower()

    # Comparative language suggests actionable insight
    comparatives = ["better", "worse", "more", "less", "higher", "lower",
                     "increase", "decrease", "improve", "reduce"]
    if any(word in content for word in comparatives):
        score += 0.1

    # Action-oriented language
    actions = ["should", "must", "recommend", "avoid", "optimize",
               "implement", "switch", "change"]
    if any(word in content for word in actions):
        score += 0.1

    # Quantified impact
    if any(ch.isdigit() for ch in content) and ("%" in content or "x " in content):
        score += 0.1

    return min(score, 1.0)
