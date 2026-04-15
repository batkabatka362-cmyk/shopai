"""Time Intelligence — memory reader.

Reads past scheduling and execution history from memory storage.
Used to inform time estimation and scheduling decisions with historical data.

Model note: Would use Qwen for structured retrieval and filtering.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_schedules(
    task_types: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Read past scheduling records, optionally filtered by task types.

    Args:
        task_types: Filter records containing these task types (None = all).
        limit: Max records to return.

    Returns:
        Structured dict with past records and summary statistics.
    """
    try:
        records = _load_records(max_files=max(limit * 5, 50))

        if task_types:
            type_set = set(task_types)
            records = [
                r for r in records
                if type_set.intersection(
                    set(r.get("task_types", []))
                )
            ]

        records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]

        summary = _compute_summary(records)

        return {
            "status": "success",
            "records": copy.deepcopy(records),
            "count": len(records),
            "summary": summary,
        }
    except Exception as exc:
        return {
            "status": "success",
            "records": [],
            "count": 0,
            "summary": {},
            "note": f"Memory read warning: {exc}",
        }


def compute_input_hash(input_data: dict[str, Any]) -> str:
    """Produce a deterministic hash for an input payload."""
    try:
        serialised = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


def find_similar_past_run(input_data: dict[str, Any]) -> dict[str, Any] | None:
    """Find a past run whose input hash matches."""
    target_hash = compute_input_hash(input_data)
    result = read_past_schedules(limit=50)
    for record in result.get("records", []):
        if record.get("input_hash", "") == target_hash:
            return copy.deepcopy(record)
    return None


def _load_records(max_files: int | None = None) -> list[dict[str, Any]]:
    """Load records from the memory directory.

    Delegates to :func:`engines._memory_base.load_recent_records` so
    every engine shares one optimised scandir walk instead of keeping
    a near-identical O(N) copy. ``max_files`` caps the read to the
    most-recently-modified N files — unset means "read everything".
    """
    from engines._memory_base import load_recent_records
    return load_recent_records(_MEMORY_DIR, max_files=max_files)


def _compute_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics over past scheduling records."""
    if not records:
        return {
            "avg_tasks_per_run": 0.0,
            "task_types_seen": [],
            "total_runs": 0,
            "avg_elapsed_seconds": 0.0,
        }

    task_counts = [r.get("task_count", 0) for r in records]
    elapsed_vals = [r.get("elapsed_seconds", 0.0) for r in records]

    all_types: set[str] = set()
    for r in records:
        all_types.update(r.get("task_types", []))

    avg_tasks = sum(task_counts) / len(task_counts) if task_counts else 0.0
    avg_elapsed = sum(elapsed_vals) / len(elapsed_vals) if elapsed_vals else 0.0

    return {
        "avg_tasks_per_run": round(avg_tasks, 2),
        "task_types_seen": sorted(all_types),
        "total_runs": len(records),
        "avg_elapsed_seconds": round(avg_elapsed, 4),
    }
