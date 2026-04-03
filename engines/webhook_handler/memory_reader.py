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

def _load_records() -> list[dict[str, Any]]:
    """Load all webhook records from the memory directory."""
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
