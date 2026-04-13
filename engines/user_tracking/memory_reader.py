"""User Tracking Engine — memory reader.

Reads past user tracking records from memory storage.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_tracking(limit: int = 10) -> dict[str, Any]:
    """Read past user tracking records."""
    try:
        records = _load_records()
        records = sorted(records, key=lambda r: r.get("timestamp", ""), reverse=True)[:limit]
        summary = _compute_summary(records)
        return {"status": "success", "records": copy.deepcopy(records), "count": len(records), "summary": summary}
    except Exception as exc:
        return {"status": "success", "records": [], "count": 0, "summary": {}, "note": f"Memory read warning: {exc}"}


def compute_input_hash(input_data: dict[str, Any]) -> str:
    try:
        serialised = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


def find_similar_past_run(input_data: dict[str, Any]) -> dict[str, Any] | None:
    target_hash = compute_input_hash(input_data)
    result = read_past_tracking(limit=50)
    for record in result.get("records", []):
        if record.get("input_hash", "") == target_hash:
            return copy.deepcopy(record)
    return None


def _load_records() -> list[dict[str, Any]]:
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
    if not records:
        return {"avg_journeys": 0.0, "avg_conversion_rate": 0.0, "total_runs": 0}
    n = len(records)
    journeys = [r.get("total_journeys", 0) for r in records]
    rates = [r.get("conversion_rate_pct", 0.0) for r in records]
    return {
        "avg_journeys": round(sum(journeys) / n, 1),
        "avg_conversion_rate": round(sum(rates) / n, 1),
        "total_runs": n,
    }
