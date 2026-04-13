"""Feedback Processing Engine — memory writer.

Persists feedback processing results to disk for future reference.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_feedback_result(
    categorized: list[dict[str, Any]],
    priorities: list[dict[str, Any]],
    trends: list[dict[str, Any]],
    recommended_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a feedback processing result record to memory.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "feedback_count": len(categorized),
            "action_count": len(recommended_actions),
            "trend_count": len(trends),
            "top_categories": _top_categories(categorized),
            "categorized": copy.deepcopy(categorized),
            "priorities": copy.deepcopy(priorities),
            "trends": copy.deepcopy(trends),
            "recommended_actions": copy.deepcopy(recommended_actions),
        }
        _ensure_memory_dir()
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


def _top_categories(categorized: list[dict[str, Any]]) -> dict[str, int]:
    """Count items per category."""
    counts: dict[str, int] = {}
    for item in categorized:
        cat = str(item.get("category", "other"))
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
