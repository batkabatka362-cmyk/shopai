"""Time Intelligence — memory writer.

Persists scheduling results and execution history to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.

Model note: Would use Qwen for structured serialization.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_schedule_result(
    input_hash: str,
    scheduled_tasks: list[dict[str, Any]],
    blocked_tasks: list[dict[str, Any]],
    delayed_tasks: list[dict[str, Any]],
    execution_order: list[str],
    timing_plan: dict[str, Any],
    task_types: list[str],
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Write a scheduling result record to memory.

    Args:
        input_hash: Hash of the original input for deduplication.
        scheduled_tasks: The final scheduled tasks list.
        blocked_tasks: Tasks that were blocked.
        delayed_tasks: Tasks that were delayed.
        execution_order: Dependency-sorted execution order.
        timing_plan: The computed timing plan.
        task_types: List of unique task types in this run.
        elapsed_seconds: Total engine elapsed time.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "input_hash": input_hash,
            "task_types": copy.deepcopy(task_types),
            "task_count": len(scheduled_tasks) + len(blocked_tasks),
            "scheduled_count": len(scheduled_tasks),
            "blocked_count": len(blocked_tasks),
            "delayed_count": len(delayed_tasks),
            "execution_order": copy.deepcopy(execution_order),
            "timing_plan": copy.deepcopy(timing_plan),
            "elapsed_seconds": round(elapsed_seconds, 4),
            "executions": [
                {
                    "task_type": _extract_type(t.get("task_id", "")),
                    "duration_seconds": t.get("estimated_duration_seconds", 0.0),
                    "priority_score": t.get("priority_score", 0.0),
                }
                for t in scheduled_tasks
            ],
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


def _extract_type(task_id: str) -> str:
    """Extract the original task type from a task_id like 'launch_ad_a1b2c3d4'."""
    parts = task_id.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) == 8:
        return parts[0]
    return task_id


def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
