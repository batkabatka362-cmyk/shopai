"""Shipping Optimization Engine — memory reader.

Reads past shipping optimization records from memory storage.
Used to inform current decisions with historical context.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_shipping(
    limit: int = 10,
) -> dict[str, Any]:
    """Read past shipping optimization records.

    Args:
        limit: Max records to return.

    Returns:
        Structured dict with past records and summary statistics.
    """
    try:
        records = _load_records(max_files=max(limit * 5, 50))

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

    Used to detect duplicate / similar shipping requests.
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
    result = read_past_shipping(limit=50)
    for record in result.get("records", []):
        if record.get("input_hash", "") == target_hash:
            return copy.deepcopy(record)
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_records(max_files: int | None = None) -> list[dict[str, Any]]:
    """Load records from the memory directory.

    Delegates to :func:`engines._memory_base.load_recent_records` so
    every engine shares one optimised scandir walk instead of keeping
    a near-identical O(N) copy. ``max_files`` caps the read to the
    most-recently-modified N files — unset means "read everything".
    """
    from engines._memory_base import load_recent_records
    return load_recent_records(_MEMORY_DIR, max_files=max_files)


def _compute_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics over past shipping records."""
    if not records:
        return {
            "avg_confidence": 0.0,
            "avg_threshold": 0.0,
            "avg_savings": 0.0,
            "strategies_used": [],
            "total_runs": 0,
        }

    confidences = [r.get("confidence", 0.0) for r in records]
    thresholds = [r.get("free_shipping_threshold", 0.0) for r in records]
    savings = [r.get("estimated_savings_monthly", 0.0) for r in records]
    strategies = list({
        r.get("recommended_strategy", {}).get("strategy_id", "unknown")
        for r in records
    })

    return {
        "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        "avg_threshold": round(sum(thresholds) / len(thresholds), 2) if thresholds else 0.0,
        "avg_savings": round(sum(savings) / len(savings), 2) if savings else 0.0,
        "strategies_used": strategies,
        "total_runs": len(records),
    }
