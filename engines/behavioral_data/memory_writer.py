"""Behavioral Data Engine — memory writer.

Persists behavioral data results to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_behavioral_result(
    behavior_summary: dict[str, Any],
    engagement_scores: list[dict[str, Any]],
    heatmaps: list[dict[str, Any]],
    top_products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a behavioral data result record to memory.

    Args:
        behavior_summary: Behavior summary dict.
        engagement_scores: List of engagement scores.
        heatmaps: List of heatmap cells.
        top_products: List of top products.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        avg_score = 0.0
        if engagement_scores:
            avg_score = round(
                sum(s.get("score", 0) for s in engagement_scores) / len(engagement_scores),
                3,
            )

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "total_sessions": behavior_summary.get("total_sessions", 0),
            "avg_engagement_score": avg_score,
            "top_products_count": len(top_products),
            "heatmap_zones": len(heatmaps),
            "outcome_actual": None,
        }

        _ensure_memory_dir()
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)

        return {
            "status": "success",
            "record_id": record_id,
            "path": fpath,
        }
    except Exception as exc:
        return {
            "status": "warning",
            "record_id": None,
            "path": None,
            "note": f"Memory write failed (non-fatal): {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
