"""Content Filter — scores and filters extracted content.

Responsibility: evaluate each ``ExtractedContent`` item for relevance,
quality, and information density, then keep only items that pass the
configurable thresholds.

Model note: no model usage — heuristic scoring.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any

from .types import ExtractedContent, FilteredContent


# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

_MIN_RELEVANCE = 0.30
_MIN_QUALITY   = 0.25
_IDEAL_WORD_COUNT = 80  # sweet-spot for a useful snippet

# Words that strongly signal useful, data-rich content
_SIGNAL_WORDS = {
    "percent", "%", "growth", "increase", "decrease", "revenue",
    "market", "trend", "data", "report", "study", "research",
    "survey", "analysis", "benchmark", "statistic", "forecast",
    "strategy", "consumer", "customer", "price", "cost",
    "roi", "conversion", "performance", "comparison",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def filter_content(
    contents: list[ExtractedContent],
    original_query: str,
    *,
    min_relevance: float = _MIN_RELEVANCE,
    min_quality: float = _MIN_QUALITY,
) -> list[FilteredContent]:
    """Score and filter content against quality and relevance thresholds.

    Never mutates *contents* — works on a deep copy.
    Returns items sorted by combined score (descending).
    """
    safe_contents: list[ExtractedContent] = copy.deepcopy(contents)
    query_tokens = set(original_query.lower().split())

    scored: list[FilteredContent] = []

    for item in safe_contents:
        text: str = item.get("text", "")
        if not text:
            continue

        relevance = _score_relevance(text, query_tokens)
        quality = _score_quality(text)

        if relevance < min_relevance or quality < min_quality:
            continue

        scored.append(
            FilteredContent(
                source_url=item.get("source_url", ""),
                source_title=item.get("source_title", ""),
                text=text,
                relevance_score=round(relevance, 3),
                quality_score=round(quality, 3),
                word_count=item.get("word_count", len(text.split())),
            )
        )

    # Sort by combined score
    scored.sort(
        key=lambda fc: fc["relevance_score"] * 0.6 + fc["quality_score"] * 0.4,
        reverse=True,
    )
    return scored


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_relevance(text: str, query_tokens: set[str]) -> float:
    """Score how relevant *text* is to the query tokens (0–1)."""
    if not query_tokens:
        return 0.5  # no query context → neutral

    text_tokens = set(text.lower().split())
    if not text_tokens:
        return 0.0

    overlap = len(query_tokens & text_tokens)
    coverage = overlap / len(query_tokens)

    # Boost for signal words
    signal_overlap = len(_SIGNAL_WORDS & text_tokens)
    signal_bonus = min(signal_overlap * 0.04, 0.25)

    return min(coverage + signal_bonus, 1.0)


def _score_quality(text: str) -> float:
    """Score the information quality of *text* (0–1)."""
    words = text.split()
    word_count = len(words)

    if word_count < 5:
        return 0.0

    # Length score — bell-curve around ideal word count
    length_score = math.exp(-0.5 * ((word_count - _IDEAL_WORD_COUNT) / 60) ** 2)

    # Lexical diversity
    unique_ratio = len(set(w.lower() for w in words)) / word_count
    diversity_score = min(unique_ratio * 1.2, 1.0)

    # Numeric density — data-rich content scores higher
    numeric_count = len(re.findall(r"\d+", text))
    numeric_score = min(numeric_count * 0.08, 0.3)

    # Sentence structure — more sentences = more structured
    sentence_count = max(len(re.split(r"[.!?]+", text)) - 1, 1)
    structure_score = min(sentence_count * 0.12, 0.3)

    quality = (
        length_score * 0.25
        + diversity_score * 0.30
        + numeric_score * 0.20
        + structure_score * 0.25
    )
    return min(quality, 1.0)
