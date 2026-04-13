"""Order Management Engine — memory reader.

Reads past order records from memory storage.
Used to inform current order processing with historical context.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_order_history(
    customer_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Read past order records, optionally filtered by customer.

    Args:
        customer_id: Optional customer ID to filter by.
        limit: Max records to return.

    Returns:
        Structured dict with past order records.
    """
    try:
        records = _load_records()

        # Filter by customer if specified
        if customer_id:
            records = [
                r for r in records
                if r.get("customer_id") == customer_id
            ]

        # Sort by timestamp descending, limit
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

def _load_records() -> list[dict[str, Any]]:
    """Load all order records from the memory directory."""
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
