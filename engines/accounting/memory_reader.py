"""Accounting Engine — memory reader.

Reads past accounting records (balances, journal entries) from memory storage.
Used to carry forward balances and provide historical context.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory", "accounting")


def read_ledger_state(
    period: dict[str, str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Read current account balances and recent journal entries from memory.

    Args:
        period: Optional period filter with "start" and "end" keys.
        limit: Max records to return.

    Returns:
        Structured dict with balances, recent entries, and count.
    """
    try:
        records = _load_records()

        # Sort by timestamp descending (most recent first)
        records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )

        # Filter by period if provided
        if period:
            start = period.get("start", "")
            end = period.get("end", "")
            if start or end:
                records = [
                    r for r in records
                    if _in_period(r.get("timestamp", ""), start, end)
                ]

        records = records[:limit]

        # Aggregate balances from most recent record
        balances: dict[str, float] = {}
        if records:
            latest = records[0]
            balances = latest.get("balances", {})

        # Collect recent journal entries across records
        recent_entries: list[dict[str, Any]] = []
        for record in records:
            entries = record.get("journal_entries", [])
            recent_entries.extend(entries)

        return {
            "status": "success",
            "balances": copy.deepcopy(balances),
            "recent_entries": copy.deepcopy(recent_entries[:limit]),
            "count": len(records),
        }
    except Exception as exc:
        return {
            "status": "success",
            "balances": {},
            "recent_entries": [],
            "count": 0,
            "note": f"Memory read warning: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_records() -> list[dict[str, Any]]:
    """Load all accounting records from the memory directory."""
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


def _in_period(timestamp: str, start: str, end: str) -> bool:
    """Check if a timestamp falls within the given period.

    Compares date prefixes (YYYY-MM-DD) of ISO timestamps.
    """
    date_part = timestamp[:10] if len(timestamp) >= 10 else timestamp
    if start and date_part < start:
        return False
    if end and date_part > end:
        return False
    return True
