"""Learning Loop — memory reader.

Reads past learning records from memory storage.
Used to inform pattern analysis and evaluation with historical context.

Model note: Would use Qwen for structured retrieval and filtering.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_records(
    task: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Read past learning records filtered by task type.

    Args:
        task: Filter by task name (empty = all).
        limit: Max records to return.

    Returns:
        Structured dict with past records and summary statistics.
    """
    try:
        records = _load_records(max_files=max(limit * 5, 50))

        if task:
            task_lower = task.lower()
            records = [
                r for r in records
                if task_lower in r.get("task", "").lower()
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


def read_records_for_decision(decision: str, limit: int = 10) -> list[dict[str, Any]]:
    """Read past records matching a specific decision string.

    Args:
        decision: Decision string to match.
        limit: Max records to return.

    Returns:
        List of matching records sorted by timestamp descending.
    """
    try:
        records = _load_records()
        decision_lower = decision.lower()
        matched = [
            r for r in records
            if decision_lower in r.get("decision", "").lower()
        ]
        matched = sorted(
            matched,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]
        return copy.deepcopy(matched)
    except Exception:
        return []


def read_all_records(limit: int = 50) -> list[dict[str, Any]]:
    """Read all past records regardless of task or decision.

    Args:
        limit: Max records to return.

    Returns:
        List of records sorted by timestamp descending.
    """
    try:
        records = _load_records()
        records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]
        return copy.deepcopy(records)
    except Exception:
        return []


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
    """Compute summary statistics over a list of past records."""
    if not records:
        return {
            "avg_score": 0.0,
            "avg_confidence": 0.0,
            "tasks_seen": [],
            "performance_distribution": {},
            "total_records": 0,
        }

    scores = [r.get("score", 0.0) for r in records if "score" in r]
    confidences = [r.get("confidence", 0.0) for r in records if "confidence" in r]
    tasks = list({r.get("task", "unknown") for r in records})

    perf_dist: dict[str, int] = {}
    for r in records:
        label = r.get("performance", "unknown")
        perf_dist[label] = perf_dist.get(label, 0) + 1

    avg_score = sum(scores) / len(scores) if scores else 0.0
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return {
        "avg_score": round(avg_score, 4),
        "avg_confidence": round(avg_confidence, 4),
        "tasks_seen": tasks,
        "performance_distribution": perf_dist,
        "total_records": len(records),
    }
