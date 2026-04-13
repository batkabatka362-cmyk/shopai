"""Cohort Analysis Engine — memory reader."""
from __future__ import annotations
import copy, hashlib, json, os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")

def read_past_cohorts(limit: int = 10) -> dict[str, Any]:
    try:
        records = _load_records()
        records = sorted(records, key=lambda r: r.get("timestamp", ""), reverse=True)[:limit]
        return {"status": "success", "records": copy.deepcopy(records), "count": len(records)}
    except Exception as exc:
        return {"status": "success", "records": [], "count": 0, "note": f"Memory read warning: {exc}"}

def compute_input_hash(input_data: dict[str, Any]) -> str:
    try:
        return hashlib.sha256(json.dumps(input_data, sort_keys=True, default=str).encode()).hexdigest()[:16]
    except Exception:
        return "unknown"

def _load_records() -> list[dict[str, Any]]:
    if not os.path.isdir(_MEMORY_DIR):
        return []
    records: list[dict[str, Any]] = []
    for fname in os.listdir(_MEMORY_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(_MEMORY_DIR, fname), "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return records
