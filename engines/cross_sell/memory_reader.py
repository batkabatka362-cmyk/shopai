"""Cross-Sell Engine — memory reader.

Retrieves past cross-sell performance data from the memory store.
Supports lookup by product ID, performance filtering, and success
rate analysis.

Model note: no model usage — pure retrieval and ranking.
"""
from __future__ import annotations

import copy
from typing import Any

from .memory_writer import get_store


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_past_cross_sells(
    product_ids: list[str] | None = None,
    *,
    min_confidence: float = 0.0,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Find past cross-sell records, optionally filtered by product IDs.

    Returns records sorted by relevance (recency + confidence),
    filtered by minimum confidence.
    Never mutates the memory store — works on copies.
    """
    store = get_store()
    if not store:
        return []

    lookup = set(product_ids) if product_ids else None

    scored: list[tuple[float, dict[str, Any]]] = []

    for record in store:
        record = copy.deepcopy(record)
        confidence = record.get("confidence", 0.0)
        if confidence < min_confidence:
            continue

        # If product_ids given, check overlap
        if lookup is not None:
            top_pids = set(record.get("top_product_ids", []))
            overlap = len(lookup & top_pids)
            if overlap == 0:
                continue
            relevance = overlap / max(len(lookup), 1)
        else:
            relevance = 0.5

        combined = confidence * 0.4 + relevance * 0.6
        if combined > 0.01:
            scored.append((combined, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in scored[:max_results]]


def get_all_cross_sells(
    *,
    min_confidence: float = 0.0,
) -> list[dict[str, Any]]:
    """Return all cross-sell records, optionally filtered by confidence."""
    store = get_store()
    results: list[dict[str, Any]] = []
    for record in store:
        if record.get("confidence", 0.0) >= min_confidence:
            results.append(copy.deepcopy(record))
    return results


def get_cross_sell_success_rates(
    *,
    min_confidence: float = 0.0,
) -> dict[str, Any]:
    """Compute aggregate success rate metrics across stored cross-sells.

    Useful for benchmarking engine performance over time.
    """
    records = get_all_cross_sells(min_confidence=min_confidence)
    if not records:
        return {
            "total_runs": 0,
            "avg_confidence": 0.0,
            "avg_aov_increase": 0.0,
            "avg_recommendations": 0.0,
        }

    count = len(records)
    avg_confidence = sum(r.get("confidence", 0.0) for r in records) / count
    avg_aov = sum(r.get("estimated_aov_increase", 0.0) for r in records) / count
    avg_recs = sum(r.get("recommendation_count", 0) for r in records) / count

    return {
        "total_runs": count,
        "avg_confidence": round(avg_confidence, 4),
        "avg_aov_increase": round(avg_aov, 2),
        "avg_recommendations": round(avg_recs, 1),
    }
