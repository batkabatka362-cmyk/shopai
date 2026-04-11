"""Social Media Engine — memory reader.

Retrieves past social media performance data from the memory store.
Supports lookup by platform, confidence filtering, and recency.

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

def find_past_performance(
    query: str,
    *,
    min_confidence: float = 0.0,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Find past performance records related to *query*.

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


def get_all_records(*, min_confidence: float = 0.0) -> list[dict[str, Any]]:
    """Return all performance records, optionally filtered by confidence."""
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
    """Compute average performance across stored records.

    Useful for benchmarking new runs against historical data.
    """
    records = get_all_records(min_confidence=min_confidence)
    if not records:
        return {
            "engagement_rate": 0.0,
            "confidence": 0.0,
            "post_count": 0.0,
            "sample_size": 0,
        }

    totals: dict[str, float] = {
        "engagement_rate": 0.0,
        "confidence": 0.0,
        "post_count": 0.0,
    }

    for r in records:
        totals["engagement_rate"] += r.get("engagement_rate", 0.0)
        totals["confidence"] += r.get("confidence", 0.0)
        totals["post_count"] += r.get("post_count", 0)

    count = len(records)
    return {
        "engagement_rate": round(totals["engagement_rate"] / count, 4),
        "confidence": round(totals["confidence"] / count, 4),
        "post_count": round(totals["post_count"] / count, 1),
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
    """Compute relevance of a record to query tokens."""
    if not query_tokens:
        return 0.0

    # Build text from record fields
    parts: list[str] = []
    parts.extend(record.get("platforms", []))
    parts.append(record.get("best_performing_type", ""))
    record_text = " ".join(parts)
    record_tokens = _tokenize(record_text)

    if not record_tokens:
        return 0.0

    overlap = len(query_tokens & record_tokens)
    query_coverage = overlap / len(query_tokens)
    record_coverage = overlap / len(record_tokens)

    return query_coverage * 0.7 + record_coverage * 0.3
