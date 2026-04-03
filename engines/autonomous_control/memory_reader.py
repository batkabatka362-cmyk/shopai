"""Autonomous Control Engine — memory reader.

Reads past autonomous control records from memory storage.
Used to inform current decisions with historical execution context.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_controls(
    limit: int = 10,
) -> dict[str, Any]:
    """Read past autonomous control records.

    Args:
        limit: Max records to return.

    Returns:
        Structured dict with past records and summary.
    """
    try:
        records = _load_records()
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


def _load_records() -> list[dict[str, Any]]:
    """Load all records from the memory directory."""
    if not os.path.isdir(_MEMORY_DIR):
        return []

    records: list[dict[str, Any]] = []
    for fname in os.listdir(_MEMORY_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(_MEMORY_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return records


def _compute_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary statistics over past control records."""
    if not records:
        return {
            "avg_approved": 0.0,
            "avg_blocked": 0.0,
            "total_runs": 0,
        }

    approved = [r.get("approved_count", 0) for r in records]
    blocked = [r.get("blocked_count", 0) for r in records]
    n = len(records)

    return {
        "avg_approved": round(sum(approved) / n, 1) if n else 0.0,
        "avg_blocked": round(sum(blocked) / n, 1) if n else 0.0,
        "total_runs": n,
    }
