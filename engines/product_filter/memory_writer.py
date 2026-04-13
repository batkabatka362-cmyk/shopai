"""Product Filter Engine — memory writer.

Persists filter decisions to disk for future reference.
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


def write_filter_result(
    accepted_products: list[dict[str, Any]],
    rejected_products: list[dict[str, Any]],
    filter_summary: dict[str, Any],
) -> dict[str, Any]:
    """Write a filter result record to memory.

    Args:
        accepted_products: Products that passed all filters.
        rejected_products: Products rejected by any filter.
        filter_summary: Summary statistics of the filter run.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "accepted_count": len(accepted_products),
            "rejected_count": len(rejected_products),
            "filter_summary": copy.deepcopy(filter_summary),
            "accepted_ids": [str(p.get("id", "")) for p in accepted_products],
            "rejection_stages": _count_by_stage(rejected_products),
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

def _count_by_stage(rejected: list[dict[str, Any]]) -> dict[str, int]:
    """Count rejections grouped by filter stage."""
    counts: dict[str, int] = {}
    for item in rejected:
        stage = str(item.get("rejection_stage", "unknown"))
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
