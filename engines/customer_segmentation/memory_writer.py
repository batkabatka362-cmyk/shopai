"""Customer Segmentation Engine — memory writer.

Persists segmentation results to disk for future reference.
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


def write_segmentation_result(
    segments: list[dict[str, Any]],
    segment_distribution: dict[str, int],
    high_value_count: int,
    at_risk_count: int,
    total_customers: int,
) -> dict[str, Any]:
    """Write a segmentation result record to memory.

    Args:
        segments: Final segment list.
        segment_distribution: Segment name to size mapping.
        high_value_count: Number of high-value customers.
        at_risk_count: Number of at-risk customers.
        total_customers: Total customers processed.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "total_customers": total_customers,
            "segment_count": len(segments),
            "segment_distribution": copy.deepcopy(segment_distribution),
            "high_value_count": high_value_count,
            "at_risk_count": at_risk_count,
            "segment_names": [s.get("name", "") for s in segments],
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


def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
