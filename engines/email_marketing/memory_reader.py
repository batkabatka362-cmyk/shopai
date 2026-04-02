"""Email Marketing Engine — memory reader.

Retrieves past campaign data from the memory store.  Supports lookup
by subject-line similarity, performance filtering, and recency.

Model note: no model usage — pure retrieval and ranking.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from .memory_writer import get_store


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_past_campaigns(
    query: str,
    *,
    min_confidence: float = 0.0,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Find past campaign records related to *query*.

    Returns records sorted by relevance (token overlap + confidence),
    filtered by minimum confidence.
    Never mutates the memory store — works on copies.
    """
    store = get_store()
    if not store or not query.strip():
        return []

    query_tokens = _tokenize(query)
    scored: list[tuple[float, dict[str, Any]]] = []

    for record in store:
        record = copy.deepcopy(record)
        confidence = record.get("confidence", 0.0)
        if confidence < min_confidence:
            continue

        relevance = _compute_relevance(query_tokens, record)
        combined = relevance * 0.6 + confidence * 0.4

        if combined > 0.05:
            scored.append((combined, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in scored[:max_results]]


def get_all_campaigns(*, min_confidence: float = 0.0) -> list[dict[str, Any]]:
    """Return all campaign records, optionally filtered by confidence."""
    store = get_store()
    results: list[dict[str, Any]] = []
    for record in store:
        if record.get("confidence", 0.0) >= min_confidence:
            results.append(copy.deepcopy(record))
    return results


def get_average_performance(
    *,
    min_confidence: float = 0.0,
) -> dict[str, float]:
    """Compute average predicted performance across stored campaigns.

    Useful for benchmarking new campaigns against historical data.
    """
    campaigns = get_all_campaigns(min_confidence=min_confidence)
    if not campaigns:
        return {
            "open_rate": 0.0,
            "click_rate": 0.0,
            "conversion_rate": 0.0,
            "unsubscribe_rate": 0.0,
            "sample_size": 0,
        }

    totals: dict[str, float] = {
        "open_rate": 0.0,
        "click_rate": 0.0,
        "conversion_rate": 0.0,
        "unsubscribe_rate": 0.0,
    }

    for c in campaigns:
        perf = c.get("predicted_performance", {})
        for key in totals:
            totals[key] += perf.get(key, 0.0)

    count = len(campaigns)
    return {
        "open_rate": round(totals["open_rate"] / count, 4),
        "click_rate": round(totals["click_rate"] / count, 4),
        "conversion_rate": round(totals["conversion_rate"] / count, 4),
        "unsubscribe_rate": round(totals["unsubscribe_rate"] / count, 4),
        "sample_size": count,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """Normalize and tokenize text for comparison."""
    text = text.lower()
    tokens = re.findall(r"\b[a-z]{2,}\b", text)
    return set(tokens)


def _compute_relevance(
    query_tokens: set[str],
    record: dict[str, Any],
) -> float:
    """Compute relevance of a campaign record to query tokens."""
    if not query_tokens:
        return 0.0

    record_text = " ".join(record.get("subject_lines", []))
    record_tokens = _tokenize(record_text)

    if not record_tokens:
        return 0.0

    overlap = len(query_tokens & record_tokens)
    query_coverage = overlap / len(query_tokens)
    record_coverage = overlap / len(record_tokens)

    return query_coverage * 0.7 + record_coverage * 0.3
