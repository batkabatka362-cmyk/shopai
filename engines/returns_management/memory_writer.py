"""Returns Management Engine — memory writer.

Persists returns processing results to disk for future reference.
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


def write_returns_result(
    processed: list[dict[str, Any]],
    reason_breakdown: list[dict[str, Any]],
    fraud_flags: list[dict[str, Any]],
    total_cost: dict[str, Any],
    return_rate: float,
) -> dict[str, Any]:
    """Write a returns result record to memory.

    Args:
        processed: List of processed return dicts.
        reason_breakdown: List of reason breakdown dicts.
        fraud_flags: List of fraud flag dicts.
        total_cost: Cost breakdown dict.
        return_rate: Overall return rate.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "processed_count": len(processed),
            "reason_breakdown": copy.deepcopy(reason_breakdown),
            "fraud_flags_count": len(fraud_flags),
            "total_cost": copy.deepcopy(total_cost),
            "return_rate": return_rate,
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
