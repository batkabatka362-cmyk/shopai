"""User Tracking Engine — memory writer.

Persists user tracking results to disk for future reference.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_tracking_result(
    journeys: list[dict[str, Any]],
    touchpoints: list[dict[str, Any]],
    attribution: list[dict[str, Any]],
    session_stats: dict[str, Any],
) -> dict[str, Any]:
    """Write a user tracking result record to memory."""
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "total_journeys": len(journeys),
            "total_touchpoints": len(touchpoints),
            "conversion_rate_pct": session_stats.get("conversion_rate_pct", 0.0),
            "outcome_actual": None,
        }
        _ensure_memory_dir()
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)
        return {"status": "success", "record_id": record_id, "path": fpath}
    except Exception as exc:
        return {"status": "warning", "record_id": None, "path": None, "note": f"Memory write failed (non-fatal): {exc}"}


def _ensure_memory_dir() -> None:
    os.makedirs(_MEMORY_DIR, exist_ok=True)
