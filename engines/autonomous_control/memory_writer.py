"""Autonomous Control Engine — memory writer.

Persists autonomous control decisions to disk for future reference.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_control_result(
    approved: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
    resource_usage: dict[str, Any],
    rollback_points: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a control result record to memory.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "approved_count": len(approved),
            "blocked_count": len(blocked),
            "resource_usage": copy.deepcopy(resource_usage),
            "rollback_points_count": len(rollback_points),
        }

        os.makedirs(_MEMORY_DIR, exist_ok=True)
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)

        return {"status": "success", "record_id": record_id, "path": fpath}
    except Exception as exc:
        return {
            "status": "warning",
            "record_id": None,
            "path": None,
            "note": f"Memory write failed (non-fatal): {exc}",
        }
