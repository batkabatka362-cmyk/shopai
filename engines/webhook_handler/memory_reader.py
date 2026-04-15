"""Webhook Handler Engine — memory reader.

Reads past webhook records from memory storage for deduplication
and historical context.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_recent_webhooks(
    limit: int = 20,
) -> dict[str, Any]:
    """Read recent webhook records from memory.

    Args:
        limit: Max records to return.

    Returns:
        Structured dict with past webhook records.
    """
    try:
        records = _load_records()

        # Sort by timestamp descending, take the most recent
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


def find_duplicate_webhook(webhook_id: str) -> dict[str, Any] | None:
    """Check if a webhook_id has already been processed.

    Args:
        webhook_id: The webhook identifier to check.

    Returns:
        The matching record dict if found, otherwise None.
    """
    if not webhook_id:
        return None

    result = read_recent_webhooks(limit=200)
    for record in result.get("records", []):
        if record.get("webhook_id") == webhook_id:
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
