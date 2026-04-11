"""Discount Strategy Engine — memory reader.

Reads past discount strategy decision records from memory storage.
Used to inform current strategy with historical context.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_discounts(
    limit: int = 10,
) -> dict[str, Any]:
    """Read past discount strategy records.

    Args:
        limit: Max records to return.

    Returns:
        Structured dict with past records and summary statistics.
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


def compute_input_hash(input_data: dict[str, Any]) -> str:
    """Produce a deterministic hash for an input payload.

    Used to detect duplicate / similar discount requests.
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
    result = read_past_discounts(limit=50)
    for record in result.get("records", []):
        if record.get("input_hash", "") == target_hash:
            return copy.deepcopy(record)
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
    """Compute summary statistics over past discount records."""
    if not records:
        return {
            "avg_confidence": 0.0,
            "avg_depth": 0.0,
            "strategies_used": [],
            "goals_served": [],
            "total_runs": 0,
        }

    confidences = [r.get("confidence", 0.0) for r in records]
    depths = [
        r.get("strategy", {}).get("depth_pct", 0.0)
        for r in records
    ]
    strategies = list({
        r.get("strategy", {}).get("type", "unknown")
        for r in records
    })
    goals = list({r.get("goal", "unknown") for r in records})

    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    avg_depth = sum(depths) / len(depths) if depths else 0.0

    return {
        "avg_confidence": round(avg_confidence, 4),
        "avg_depth": round(avg_depth, 4),
        "strategies_used": strategies,
        "goals_served": goals,
        "total_runs": len(records),
    }
