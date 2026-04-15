"""A/B Testing -- memory reader.

Reads past A/B test result records from memory storage.
Used to inform current tests with historical context.

Model note: Would use Qwen for structured retrieval and filtering.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_tests(
    test_type: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Read past A/B test records, optionally filtered by test type.

    Args:
        test_type: Filter by test type (None = all).
        limit: Max records to return.

    Returns:
        Structured dict with past records and summary statistics.
    """
    try:
        records = _load_records(max_files=max(limit * 5, 50))

        if test_type:
            records = [r for r in records if r.get("test_type") == test_type]

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
        serialized = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


def find_similar_past_run(input_data: dict[str, Any]) -> dict[str, Any] | None:
    """Find a past run whose input hash matches.

    Returns the matching record or None.
    """
    target_hash = compute_input_hash(input_data)
    result = read_past_tests(limit=50)
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
    """Compute summary statistics over a list of past test records."""
    if not records:
        return {
            "avg_confidence": 0.0,
            "total_tests": 0,
            "winners_found": 0,
            "test_types": [],
            "avg_p_value": 0.0,
        }

    confidences = [r.get("confidence", 0.0) for r in records]
    p_values = [
        r.get("analysis", {}).get("p_value", 1.0) for r in records
    ]
    winners = sum(
        1 for r in records
        if r.get("winner", {}).get("winner", "no_winner") != "no_winner"
    )
    test_types = list({r.get("test_type", "unknown") for r in records})

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    avg_p = sum(p_values) / len(p_values) if p_values else 1.0

    return {
        "avg_confidence": round(avg_conf, 4),
        "total_tests": len(records),
        "winners_found": winners,
        "test_types": test_types,
        "avg_p_value": round(avg_p, 6),
    }
