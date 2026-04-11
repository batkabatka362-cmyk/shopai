"""Product Lifecycle Engine — memory writer.

Persists lifecycle assessment results to disk for future reference.
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


def write_lifecycle_result(
    lifecycle: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a lifecycle result record to memory.

    Args:
        lifecycle: List of per-product lifecycle assessment dicts.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        stage_counts: dict[str, int] = {}
        for item in lifecycle:
            stage = str(item.get("stage", "unknown"))
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "lifecycle": copy.deepcopy(lifecycle),
            "product_count": len(lifecycle),
            "stage_distribution": stage_counts,
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
