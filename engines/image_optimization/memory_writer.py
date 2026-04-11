"""Image Optimization Engine — memory writer.

Persists image optimization decisions to disk for future reference.
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


def write_optimization_result(
    optimizations: list[dict[str, Any]],
    gallery_order: list[dict[str, Any]],
    missing_types: list[str],
    quality_scores: dict[str, Any],
) -> dict[str, Any]:
    """Write an image optimization result record to memory.

    Args:
        optimizations: List of per-image optimization results.
        gallery_order: Planned gallery order.
        missing_types: List of missing image types.
        quality_scores: Aggregate quality scores.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        avg_savings = 0.0
        if optimizations:
            savings_vals = [o.get("savings_pct", 0.0) for o in optimizations]
            avg_savings = round(sum(savings_vals) / len(savings_vals), 1) if savings_vals else 0.0

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "images_optimized": len(optimizations),
            "gallery_positions": len(gallery_order),
            "missing_types": missing_types,
            "avg_quality_score": quality_scores.get("average_score", 0.0),
            "avg_savings_pct": avg_savings,
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
