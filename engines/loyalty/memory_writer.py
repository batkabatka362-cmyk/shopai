"""Loyalty Engine — memory writer.

Persists loyalty program decisions to disk for future reference.
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


def write_loyalty_result(
    customer_status: list[dict[str, Any]],
    program_health: dict[str, Any],
    reward_recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a loyalty result record to memory.

    Args:
        customer_status: List of customer tier status dicts.
        program_health: Program health metrics dict.
        reward_recommendations: List of reward recommendation dicts.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "total_members": program_health.get("total_members", 0),
            "active_members": program_health.get("active_members", 0),
            "total_points_outstanding": program_health.get("total_points_outstanding", 0),
            "tier_distribution": program_health.get("tier_distribution", {}),
            "recommendations_count": len(reward_recommendations),
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
