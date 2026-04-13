"""Upsell Engine — memory reader.

Reads past upsell performance records from memory storage.
Used to inform current recommendations with historical success rates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_upsells(
    limit: int = 10,
    category: str | None = None,
) -> dict[str, Any]:
    """Read past upsell performance records.

    Args:
        limit: Max records to return.
        category: Optional category filter.

    Returns:
        Structured dict with past records and summary statistics.
    """
    try:
        records = _load_records()

        # Optional category filter
        if category:
            cat_lower = category.lower().strip()
            records = [
                r for r in records
                if str(r.get("category", "")).lower().strip() == cat_lower
            ]

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


def compute_input_hash(input_data: dict[str, Any]) -> str:
    """Produce a deterministic hash for an input payload.

    Used to detect duplicate / similar upsell requests.
    """
    try:
        serialised = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


def find_similar_past_run(input_data: dict[str, Any]) -> dict[str, Any] | None:
    """Find a past run whose input hash matches.

    Returns the matching record or None.
    """
    target_hash = compute_input_hash(input_data)
    result = read_past_upsells(limit=50)
    for record in result.get("records", []):
        if record.get("input_hash", "") == target_hash:
            return copy.deepcopy(record)
    return None


def get_category_success_rate(category: str) -> float:
    """Get historical upsell success rate for a category.

    Returns the average confidence from past runs, or 0.0 if no data.
    """
    result = read_past_upsells(limit=100, category=category)
    records = result.get("records", [])
    if not records:
        return 0.0

    confidences = [float(r.get("confidence", 0.0)) for r in records]
    return sum(confidences) / len(confidences)


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
    """Compute summary statistics over past upsell records."""
    if not records:
        return {
            "avg_confidence": 0.0,
            "avg_revenue_increase": 0.0,
            "avg_candidates_recommended": 0.0,
            "categories_served": [],
            "total_runs": 0,
        }

    confidences = [r.get("confidence", 0.0) for r in records]
    revenues = [r.get("estimated_revenue_increase", 0.0) for r in records]
    rec_counts = [r.get("candidates_recommended", 0) for r in records]
    categories = list({
        str(r.get("category", "unknown")) for r in records
    })

    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    avg_revenue = sum(revenues) / len(revenues) if revenues else 0.0
    avg_rec = sum(rec_counts) / len(rec_counts) if rec_counts else 0.0

    return {
        "avg_confidence": round(avg_confidence, 4),
        "avg_revenue_increase": round(avg_revenue, 2),
        "avg_candidates_recommended": round(avg_rec, 1),
        "categories_served": categories,
        "total_runs": len(records),
    }
