"""Inventory Engine — memory writer.

Persists inventory decisions to disk for future reference.
Each run is stored as a separate JSON file keyed by record_id.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_inventory_result(
    inventory_health: dict[str, Any],
    reorder_plan: list[dict[str, Any]],
    stockout_risks: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    cost_summary: dict[str, Any],
) -> dict[str, Any]:
    """Write an inventory result record to memory.

    Args:
        inventory_health: Inventory health summary dict.
        reorder_plan: List of reorder plan items.
        stockout_risks: List of stockout risk dicts.
        alerts: List of alert dicts.
        cost_summary: Cost summary dict.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "inventory_health": copy.deepcopy(inventory_health),
            "reorder_plan": copy.deepcopy(reorder_plan),
            "stockout_risks": copy.deepcopy(stockout_risks),
            "alerts_count": len(alerts),
            "alerts_by_severity": _count_by_severity(alerts),
            "cost_summary": copy.deepcopy(cost_summary),
            "outcome_actual": None,
        }

        _ensure_memory_dir()
        fpath = os.path.join(_MEMORY_DIR, f"{record_id}.json")
        with open(fpath, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, default=str)

        return {
            "status": "success",
            "record_id": record_id,
            "path": fpath,
        }
    except Exception as exc:
        return {
            "status": "warning",
            "record_id": None,
            "path": None,
            "note": f"Memory write failed (non-fatal): {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _count_by_severity(alerts: list[dict[str, Any]]) -> dict[str, int]:
    """Count alerts grouped by severity level."""
    counts: dict[str, int] = {}
    for alert in alerts:
        sev = str(alert.get("severity", "unknown"))
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
