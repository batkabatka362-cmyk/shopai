"""Review Management Engine — memory reader.

Reads past review analysis records from memory storage.
Used to compare current review health against historical trends.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_analyses(
    product_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Read past review analysis records.

    Args:
        product_id: Optional filter by product. None returns all.
        limit: Max records to return.

    Returns:
        Structured dict with past records and summary statistics.
    """
    try:
        records = _load_records()

        # Filter by product if specified
        if product_id is not None:
            records = [r for r in records if r.get("product_id") == product_id]

        # Sort by timestamp descending, take latest
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
    """Load all records from the memory directory."""
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
    """Compute summary statistics over past review analysis records."""
    if not records:
        return {
            "avg_confidence": 0.0,
            "avg_rating_over_time": 0.0,
            "trend_directions": [],
            "total_runs": 0,
        }

    confidences = [r.get("confidence", 0.0) for r in records]
    ratings = [r.get("avg_rating", 0.0) for r in records]
    trends = list({r.get("trend_direction", "unknown") for r in records})

    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    avg_rating = sum(ratings) / len(ratings) if ratings else 0.0

    return {
        "avg_confidence": round(avg_confidence, 4),
        "avg_rating_over_time": round(avg_rating, 2),
        "trend_directions": trends,
        "total_runs": len(records),
    }
