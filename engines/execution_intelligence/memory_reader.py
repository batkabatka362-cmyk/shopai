"""Execution Intelligence — memory reader.

Reads past execution records from memory storage.
Used to inform current executions with historical context.

Model note: Would use Qwen for structured retrieval and filtering.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_executions(
    action_type: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Read past execution records, optionally filtered by action type.

    Args:
        action_type: Filter to records containing this action type (empty = all).
        limit: Max records to return.

    Returns:
        Structured dict with past records and summary statistics.
    """
    try:
        records = _load_records(max_files=max(limit * 5, 50))

        if action_type:
            records = [
                r for r in records
                if action_type in r.get("action_types", [])
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
    """Produce a deterministic hash for an input payload.

    Used to detect duplicate / similar execution requests.
    """
    try:
        serialised = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


def find_similar_past_run(input_data: dict[str, Any]) -> dict[str, Any] | None:
    """Find a past run whose input hash matches.

    Returns the matching record or None.
    """
    target_hash = compute_input_hash(input_data)
    result = read_past_executions(limit=50)
    for record in result.get("records", []):
        if record.get("input_hash", "") == target_hash:
            return copy.deepcopy(record)
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
            "avg_success_rate": 0.0,
            "action_types_seen": [],
            "total_runs": 0,
        }

    success_rates = [float(r.get("success_rate", 0.0)) for r in records]
    all_action_types: set[str] = set()
    for r in records:
        for at in r.get("action_types", []):
            all_action_types.add(at)

    avg_rate = sum(success_rates) / len(success_rates) if success_rates else 0.0

    return {
        "avg_success_rate": round(avg_rate, 4),
        "action_types_seen": sorted(all_action_types),
        "total_runs": len(records),
    }
