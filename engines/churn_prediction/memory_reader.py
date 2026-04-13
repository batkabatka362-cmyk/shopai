"""Churn Prediction Engine — memory reader.

Retrieves past churn prediction data from the memory store.  Supports
lookup by customer ID, performance filtering, and accuracy tracking
across prediction batches.

Model note: no model usage — pure retrieval and ranking.
"""
from __future__ import annotations

import copy
from typing import Any

from .memory_writer import get_store


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_past_predictions(
    customer_id: str,
    *,
    min_confidence: float = 0.0,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Find past prediction records for a specific customer.

    Searches all stored batches for predictions matching *customer_id*.
    Returns individual prediction records sorted by confidence descending,
    filtered by minimum confidence.
    Never mutates the memory store — works on copies.
    """
    store = get_store()
    if not store:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []

    for batch in store:
        batch = copy.deepcopy(batch)
        batch_confidence = batch.get("confidence", 0.0)

        if batch_confidence < min_confidence:
            continue

        predictions = batch.get("predictions", [])
        for pred in predictions:
            if pred.get("customer_id") == customer_id:
                pred["batch_confidence"] = batch_confidence
                pred["batch_timestamp"] = batch.get("timestamp", "")
                score = batch_confidence * 0.4 + pred.get("churn_probability", 0.0) * 0.6
                scored.append((score, pred))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in scored[:max_results]]


def get_all_predictions(*, min_confidence: float = 0.0) -> list[dict[str, Any]]:
    """Return all prediction batch records, optionally filtered by confidence."""
    store = get_store()
    results: list[dict[str, Any]] = []
    for batch in store:
        if batch.get("confidence", 0.0) >= min_confidence:
            results.append(copy.deepcopy(batch))
    return results


def get_risk_distribution(
    *,
    min_confidence: float = 0.0,
) -> dict[str, dict[str, float]]:
    """Compute aggregate statistics by risk level across stored predictions.

    Useful for tracking how risk distribution changes over time and
    measuring prediction accuracy.
    """
    batches = get_all_predictions(min_confidence=min_confidence)
    if not batches:
        return {}

    risk_data: dict[str, list[dict[str, Any]]] = {}
    for batch in batches:
        for pred in batch.get("predictions", []):
            level = pred.get("risk_level", "unknown")
            risk_data.setdefault(level, []).append(pred)

    result: dict[str, dict[str, float]] = {}
    for level, records in risk_data.items():
        count = len(records)
        avg_prob = sum(r.get("churn_probability", 0.0) for r in records) / count
        result[level] = {
            "avg_churn_probability": round(avg_prob, 4),
            "count": count,
        }

    return result
