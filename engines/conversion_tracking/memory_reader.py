"""Conversion Tracking Engine — memory reader.

Reads past conversion tracking records from memory storage.
Used to inform current analysis with historical context.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_conversions(
    limit: int = 10,
) -> dict[str, Any]:
    """Read past conversion tracking records.

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
    """Produce a deterministic hash for an input payload."""
    try:
        serialised = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


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
    """Compute summary statistics over past conversion records."""
    if not records:
        return {
            "avg_conversion_count": 0.0,
            "avg_total_value": 0.0,
            "total_runs": 0,
        }

    conv_counts = [len(r.get("conversions", [])) for r in records]
    total_values = [
        sum(float(c.get("value", 0)) for c in r.get("conversions", []))
        for r in records
    ]

    n = len(records)
    return {
        "avg_conversion_count": round(sum(conv_counts) / n, 1) if n else 0.0,
        "avg_total_value": round(sum(total_values) / n, 2) if n else 0.0,
        "total_runs": n,
    }
