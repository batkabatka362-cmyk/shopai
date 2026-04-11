"""Conversion Tracking Engine — memory writer.

Persists conversion tracking results to disk for future reference.
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


def write_conversion_result(
    conversions: list[dict[str, Any]],
    funnel: dict[str, Any],
    goal_progress: list[dict[str, Any]],
    attribution_report: dict[str, float],
) -> dict[str, Any]:
    """Write a conversion tracking result record to memory.

    Args:
        conversions: List of conversion result dicts.
        funnel: Funnel analysis dict.
        goal_progress: List of goal progress dicts.
        attribution_report: Attribution report dict.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "conversions": copy.deepcopy(conversions),
            "funnel": copy.deepcopy(funnel),
            "goal_progress": copy.deepcopy(goal_progress),
            "attribution_report": copy.deepcopy(attribution_report),
            "conversion_count": len(conversions),
            "total_value": sum(float(c.get("value", 0)) for c in conversions),
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
