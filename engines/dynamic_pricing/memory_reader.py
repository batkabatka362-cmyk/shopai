"""Dynamic Pricing Engine — memory reader.

Reads past pricing change records from memory storage.
Used for 24-hour change window enforcement and historical context.

1 file = 1 job: read pricing change history only.
"""
from __future__ import annotations

import copy
import json
import os
import time
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_recent_changes(
    product_id: str | None = None,
    hours: float = 24.0,
    limit: int = 50,
) -> dict[str, Any]:
    """Read recent pricing change records, optionally filtered by product.

    Args:
        product_id: Optional product ID to filter by.
        hours: Time window in hours (default 24).
        limit: Max records to return.

    Returns:
        Structured dict with recent change records.
    """
    try:
        records = _load_records()

        # Filter by time window
        cutoff = time.time() - (hours * 3600)
        recent: list[dict[str, Any]] = []
        for rec in records:
            ts_str = rec.get("timestamp", "")
            try:
                rec_time = time.mktime(time.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ"))
                if rec_time >= cutoff:
                    recent.append(rec)
            except (ValueError, OverflowError):
                continue

        # Filter by product_id if specified
        if product_id is not None:
            recent = [r for r in recent if r.get("product_id") == product_id]

        # Sort by timestamp descending, limit
        recent = sorted(
            recent,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]

        return {
            "status": "success",
            "records": copy.deepcopy(recent),
            "count": len(recent),
        }
    except Exception as exc:
        return {
            "status": "success",
            "records": [],
            "count": 0,
            "note": f"Memory read warning: {exc}",
        }


def read_all_changes(limit: int = 100) -> dict[str, Any]:
    """Read all pricing change records (no time filter).

    Args:
        limit: Max records to return.

    Returns:
        Structured dict with all change records.
    """
    try:
        records = _load_records()
        records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]

        return {
            "status": "success",
            "records": copy.deepcopy(records),
            "count": len(records),
        }
    except Exception as exc:
        return {
            "status": "success",
            "records": [],
            "count": 0,
            "note": f"Memory read warning: {exc}",
        }


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
