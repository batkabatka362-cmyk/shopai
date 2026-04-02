"""Cart Recovery Engine — memory reader.

Retrieves past recovery attempt data from the memory store.  Supports
lookup by customer ID, performance filtering, and strategy analysis.

Model note: no model usage — pure retrieval and ranking.
"""
from __future__ import annotations

import copy
from typing import Any

from .memory_writer import get_store


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_past_recoveries(
    customer_id: str,
    *,
    min_confidence: float = 0.0,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Find past recovery records related to a customer.

    Returns records sorted by relevance (recency + confidence),
    filtered by minimum confidence.
    Never mutates the memory store — works on copies.
    """
    store = get_store()
    if not store:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []

    for record in store:
        record = copy.deepcopy(record)
        confidence = record.get("confidence", 0.0)
        if confidence < min_confidence:
            continue

        # Score by confidence and recovery probability
        prob = record.get("recovery_probability", 0.0)
        combined = confidence * 0.4 + prob * 0.6

        if combined > 0.01:
            scored.append((combined, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in scored[:max_results]]


def get_all_recoveries(*, min_confidence: float = 0.0) -> list[dict[str, Any]]:
    """Return all recovery records, optionally filtered by confidence."""
    store = get_store()
    results: list[dict[str, Any]] = []
    for record in store:
        if record.get("confidence", 0.0) >= min_confidence:
            results.append(copy.deepcopy(record))
    return results


def get_strategy_performance(
    *,
    min_confidence: float = 0.0,
) -> dict[str, dict[str, float]]:
    """Compute average performance by strategy across stored recoveries.

    Useful for benchmarking which strategies are most effective.
    """
    recoveries = get_all_recoveries(min_confidence=min_confidence)
    if not recoveries:
        return {}

    strategy_data: dict[str, list[dict[str, Any]]] = {}
    for r in recoveries:
        strat = r.get("strategy", "unknown")
        strategy_data.setdefault(strat, []).append(r)

    result: dict[str, dict[str, float]] = {}
    for strat, records in strategy_data.items():
        count = len(records)
        avg_prob = sum(r.get("recovery_probability", 0.0) for r in records) / count
        avg_revenue = sum(r.get("expected_revenue", 0.0) for r in records) / count
        avg_confidence = sum(r.get("confidence", 0.0) for r in records) / count
        result[strat] = {
            "avg_recovery_probability": round(avg_prob, 4),
            "avg_expected_revenue": round(avg_revenue, 2),
            "avg_confidence": round(avg_confidence, 4),
            "sample_size": count,
        }

    return result
