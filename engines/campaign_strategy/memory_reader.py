"""Campaign Strategy Engine — memory reader.

Reads past campaign strategy records from memory storage.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_past_campaigns(limit: int = 10) -> dict[str, Any]:
    try:
        records = _load_records(max_files=max(limit * 5, 50))
        records = sorted(records, key=lambda r: r.get("timestamp", ""), reverse=True)[:limit]
        return {"status": "success", "records": copy.deepcopy(records), "count": len(records)}
    except Exception as exc:
        return {"status": "success", "records": [], "count": 0, "note": f"Memory read warning: {exc}"}


def compute_input_hash(input_data: dict[str, Any]) -> str:
    try:
        serialised = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


def _load_records(max_files: int | None = None) -> list[dict[str, Any]]:
    """Load records from the memory directory.

    Delegates to :func:`engines._memory_base.load_recent_records` so
    every engine shares one optimised scandir walk instead of keeping
    a near-identical O(N) copy. ``max_files`` caps the read to the
    most-recently-modified N files — unset means "read everything".
    """
    from engines._memory_base import load_recent_records
    return load_recent_records(_MEMORY_DIR, max_files=max_files)
