"""Feature Builder — transforms filtered content into structured features.

Responsibility: take ``FilteredContent`` items and decompose them into
discrete ``ResearchFeature`` records — each representing a single claim,
statistic, or insight with its supporting evidence and a strength score.

This is the ONLY gateway between raw/filtered content and the analysis
layer.  Downstream modules (analyzer, synthesizer) must consume features,
never raw content.

Model note: would use **Qwen** for structured feature extraction.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from .types import FilteredContent, ResearchFeature


# ---------------------------------------------------------------------------
# Category detection patterns
# ---------------------------------------------------------------------------

_STAT_PATTERN = re.compile(
    r"\d+[\d,]*\.?\d*\s*%"           # percentages
    r"|\$\s*\d+[\d,]*\.?\d*"         # dollar amounts
    r"|\d+[\d,]*\.?\d*\s*(?:x|times)"  # multipliers
    r"|\d+[\d,]*\.?\d*\s*(?:billion|million|thousand|mn|bn|k)\b",
    re.IGNORECASE,
)

_TREND_KEYWORDS = {
    "growing", "declining", "increasing", "decreasing", "rising",
    "falling", "surging", "emerging", "shifting", "expanding",
    "accelerating", "slowing", "stabilising", "stabilizing",
}

_OPINION_MARKERS = {
    "believe", "suggest", "recommend", "argue", "claim",
    "opinion", "likely", "could", "might", "may", "should",
    "expected", "projected", "estimated", "predicted",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_features(
    filtered: list[FilteredContent],
    original_query: str,
) -> list[ResearchFeature]:
    """Convert filtered content into structured research features.

    Never mutates *filtered* — works on a deep copy.
    Returns a flat list of ``ResearchFeature`` dicts, one per extractable
    claim found in the input content.
    """
    safe_filtered: list[FilteredContent] = copy.deepcopy(filtered)

    if not safe_filtered:
        return []

    query_tokens = set(original_query.lower().split())
    features: list[ResearchFeature] = []

    for item in safe_filtered:
        text: str = item.get("text", "")
        source_url: str = item.get("source_url", "")
        relevance: float = item.get("relevance_score", 0.5)
        quality: float = item.get("quality_score", 0.5)

        if not text:
            continue

        sentences = _split_sentences(text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence.split()) < 4:
                continue

            category = _classify_sentence(sentence)
            claim = _extract_claim(sentence)
            strength = _compute_strength(
                sentence, query_tokens, relevance, quality, category,
            )

            feature_id = _make_id(source_url, claim)

            features.append(
                ResearchFeature(
                    feature_id=feature_id,
                    source_url=source_url,
                    claim=claim,
                    evidence=sentence,
                    category=category,
                    strength=round(strength, 3),
                )
            )

    # Deduplicate by feature_id
    features = _deduplicate(features)

    # Sort strongest first
    features.sort(key=lambda f: f["strength"], reverse=True)

    return features


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on period/exclamation/question boundaries."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p for p in parts if p.strip()]


def _classify_sentence(sentence: str) -> str:
    """Classify a sentence as fact, statistic, trend, or opinion."""
    lower = sentence.lower()
    tokens = set(lower.split())

    # Statistics take priority — they contain hard numbers
    if _STAT_PATTERN.search(sentence):
        return "statistic"

    # Trend language
    if tokens & _TREND_KEYWORDS:
        return "trend"

    # Opinion markers
    if tokens & _OPINION_MARKERS:
        return "opinion"

    return "fact"


def _extract_claim(sentence: str) -> str:
    """Distil a sentence down to its core claim.

    For now, returns a cleaned version of the sentence.  In production
    this would call Qwen for abstractive extraction.
    """
    # Remove leading connectives
    claim = re.sub(
        r"^(?:however|moreover|additionally|furthermore|also|in addition)[,;]?\s*",
        "",
        sentence,
        flags=re.IGNORECASE,
    )
    # Trim trailing whitespace / stray punctuation
    claim = claim.strip().rstrip(",;")
    # Capitalise first letter
    if claim:
        claim = claim[0].upper() + claim[1:]
    return claim


def _compute_strength(
    sentence: str,
    query_tokens: set[str],
    relevance: float,
    quality: float,
    category: str,
) -> float:
    """Compute a 0–1 strength score for a single feature.

    Factors:
    * query overlap — does the sentence address the research goal?
    * source scores — inherited relevance and quality from the filter step
    * category weight — statistics and trends score higher than opinions
    * evidence density — longer, data-rich sentences score higher
    """
    # Query overlap component
    sent_tokens = set(sentence.lower().split())
    overlap = len(query_tokens & sent_tokens) / max(len(query_tokens), 1)
    overlap_score = min(overlap, 1.0)

    # Category weighting
    cat_weights = {
        "statistic": 0.95,
        "trend": 0.80,
        "fact": 0.65,
        "opinion": 0.45,
    }
    cat_score = cat_weights.get(category, 0.5)

    # Evidence density (word count normalised)
    word_count = len(sentence.split())
    density = min(word_count / 25.0, 1.0)

    # Weighted combination
    strength = (
        overlap_score * 0.25
        + relevance * 0.20
        + quality * 0.15
        + cat_score * 0.25
        + density * 0.15
    )
    return min(strength, 1.0)


def _make_id(source_url: str, claim: str) -> str:
    """Deterministic feature ID from source + claim."""
    raw = f"{source_url}|{claim}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _deduplicate(features: list[ResearchFeature]) -> list[ResearchFeature]:
    """Remove features with duplicate IDs, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[ResearchFeature] = []
    for f in features:
        fid = f["feature_id"]
        if fid not in seen:
            seen.add(fid)
            unique.append(f)
    return unique
