"""Customer Segmentation Engine — memory reader.

Reads past segmentation history from memory storage.
Used to track segment drift and inform strategy adjustments.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_segmentations(
    limit: int = 10,
) -> dict[str, Any]:
    """Read past segmentation records.

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
    """Compute summary statistics over past segmentation records."""
    if not records:
        return {
            "avg_customers": 0,
            "avg_segments": 0,
            "avg_high_value_pct": 0.0,
            "avg_at_risk_pct": 0.0,
            "total_runs": 0,
        }

    customers = [r.get("total_customers", 0) for r in records]
    seg_counts = [r.get("segment_count", 0) for r in records]
    hv_pcts = []
    ar_pcts = []

    for r in records:
        total = r.get("total_customers", 1) or 1
        hv_pcts.append(r.get("high_value_count", 0) / total)
        ar_pcts.append(r.get("at_risk_count", 0) / total)

    def _avg(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    return {
        "avg_customers": round(_avg(customers), 1),
        "avg_segments": round(_avg(seg_counts), 1),
        "avg_high_value_pct": round(_avg(hv_pcts), 4),
        "avg_at_risk_pct": round(_avg(ar_pcts), 4),
        "total_runs": len(records),
    }
