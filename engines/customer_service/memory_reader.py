"""Customer Service Engine — memory reader.

Reads past customer interaction records from memory storage.
Used to inform current responses with historical context.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_interaction_history(
    customer_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Read past interaction records, optionally filtered by customer.

    Args:
        customer_id: Optional customer ID to filter records.
        limit: Max records to return.

    Returns:
        Structured dict with past interaction records and summary.
    """
    try:
        records = _load_records()

        # Filter by customer_id if provided
        if customer_id:
            records = [
                r for r in records
                if str(r.get("customer_id", "")) == customer_id
            ]

        # Sort by timestamp descending, take most recent
        records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]

        summary = _compute_summary(records)

        return {
            "status": "success",
            "records": copy.deepcopy(records),
            "count": len(records),
            "summary": summary,
        }
    except Exception as exc:
        return {
            "status": "success",
            "records": [],
            "count": 0,
            "summary": {},
            "note": f"Memory read warning: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_records() -> list[dict[str, Any]]:
    """Load all interaction records from the memory directory."""
    if not os.path.isdir(_MEMORY_DIR):
        return []

    records: list[dict[str, Any]] = []
    for fname in os.listdir(_MEMORY_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(_MEMORY_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return records


def _compute_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics over past interaction records."""
    if not records:
        return {
            "total_interactions": 0,
            "escalation_rate": 0.0,
            "top_intents": {},
            "avg_satisfaction": 0.0,
        }

    n = len(records)

    # Escalation rate
    escalated_count = sum(1 for r in records if r.get("escalated", False))
    escalation_rate = round(escalated_count / n, 2) if n else 0.0

    # Top intents
    intent_counts: dict[str, int] = {}
    for r in records:
        intent = str(r.get("intent", "unknown"))
        intent_counts[intent] = intent_counts.get(intent, 0) + 1

    # Average satisfaction (if tracked)
    sat_scores = [
        float(r.get("satisfaction_score", 0.0))
        for r in records
        if r.get("satisfaction_score") is not None
    ]
    avg_satisfaction = (
        round(sum(sat_scores) / len(sat_scores), 2)
        if sat_scores else 0.0
    )

    return {
        "total_interactions": n,
        "escalation_rate": escalation_rate,
        "top_intents": intent_counts,
        "avg_satisfaction": avg_satisfaction,
    }
