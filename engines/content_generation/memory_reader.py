"""Content Generation Engine — memory reader.

Reads past content generation records from memory storage.
Used to track content performance and inform future generation.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_content(
    limit: int = 10,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Read past content generation records.

    Args:
        limit: Max records to return.
        content_type: Optional filter by content type.

    Returns:
        Structured dict with past records and summary statistics.
    """
    try:
        records = _load_records(max_files=max(limit * 5, 50))

        # Filter by content type if specified
        if content_type:
            ct = content_type.strip().lower()
            records = [r for r in records if r.get("content_type", "") == ct]

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
    """Compute summary statistics over past content records."""
    if not records:
        return {
            "avg_seo_score": 0.0,
            "avg_readability": 0.0,
            "avg_confidence": 0.0,
            "content_type_distribution": {},
            "total_runs": 0,
        }

    seo_scores = [r.get("seo_score", 0.0) for r in records]
    readability_scores = [r.get("readability_score", 0.0) for r in records]
    confidences = [r.get("confidence", 0.0) for r in records]

    # Content type distribution
    ct_dist: dict[str, int] = {}
    for r in records:
        ct = r.get("content_type", "unknown")
        ct_dist[ct] = ct_dist.get(ct, 0) + 1

    def _avg(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    return {
        "avg_seo_score": round(_avg(seo_scores), 2),
        "avg_readability": round(_avg(readability_scores), 2),
        "avg_confidence": round(_avg(confidences), 2),
        "content_type_distribution": ct_dist,
        "total_runs": len(records),
    }
