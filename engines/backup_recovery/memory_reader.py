"""Backup/Recovery Engine — memory reader.

Lists past backup records from the engine's .memory/ directory.
Used to provide backup history and inform decisions.
"""
from __future__ import annotations

import json
import os
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def read_backup_history(
    limit: int = 10,
) -> dict[str, Any]:
    """Read past backup metadata records.

    Args:
        limit: Max number of records to return.

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

        # Project to summary entries
        backups: list[dict[str, Any]] = []
        for record in records:
            backups.append({
                "backup_id": record.get("backup_id", ""),
                "timestamp": record.get("timestamp", ""),
                "size": record.get("final_size_bytes", 0),
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

def _load_records(max_files: int | None = None) -> list[dict[str, Any]]:
    """Load records from the memory directory.

    Delegates to :func:`engines._memory_base.load_recent_records` so
    every engine shares one optimised scandir walk instead of keeping
    a near-identical O(N) copy. ``max_files`` caps the read to the
    most-recently-modified N files — unset means "read everything".
    """
    from engines._memory_base import load_recent_records
    return load_recent_records(_MEMORY_DIR, max_files=max_files)
