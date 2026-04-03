"""Backup/Recovery Engine — memory reader.

Lists past backup metadata from .memory/backup_recovery/ directory.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_backup_history(
    limit: int = 10,
) -> dict[str, Any]:
    """List past backups from memory storage.

    Args:
        limit: Max number of backup records to return.

    Returns:
        Structured dict with backup history entries.
    """
    try:
        records = _load_records()

        # Sort by timestamp descending (most recent first)
        records = sorted(
            records,
            key=lambda r: r.get("timestamp", ""),
            reverse=True,
        )[:limit]

        # Map to summary entries
        backups: list[dict[str, Any]] = []
        for record in records:
            backups.append({
                "backup_id": record.get("backup_id", ""),
                "timestamp": record.get("timestamp", ""),
                "size": record.get("size_bytes", 0),
                "records": record.get("total_records", 0),
            })

        return {
            "status": "success",
            "backups": backups,
            "count": len(backups),
        }
    except Exception as exc:
        return {
            "status": "success",
            "backups": [],
            "count": 0,
            "note": f"Memory read warning: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_records() -> list[dict[str, Any]]:
    """Load all backup metadata records from the memory directory."""
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
