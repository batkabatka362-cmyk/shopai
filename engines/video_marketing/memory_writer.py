"""Video Marketing Engine — memory writer.

Persists video marketing decisions to disk for future reference.
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


def write_video_result(
    script: dict[str, Any],
    storyboard: list[dict[str, Any]],
    platform: str,
    engagement: dict[str, Any],
) -> dict[str, Any]:
    """Write a video marketing result record to memory.

    Args:
        script: Generated script dict.
        storyboard: List of storyboard scene dicts.
        platform: Target platform.
        engagement: Estimated engagement metrics.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "platform": platform,
            "duration_seconds": script.get("duration", 0),
            "scenes_count": len(storyboard),
            "estimated_views": engagement.get("estimated_views", 0),
            "engagement_rate": engagement.get("engagement_rate", 0.0),
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
