"""Marketplace Engine — memory writer.

Persists marketplace sync decisions to disk for future reference.
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


def write_marketplace_result(
    sync_status: list[dict[str, Any]],
    price_adjustments: list[dict[str, Any]],
    inventory_allocation: list[dict[str, Any]],
    performance: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a marketplace result record to memory.

    Args:
        sync_status: Per-platform listing sync results.
        price_adjustments: Price adjustment recommendations.
        inventory_allocation: Per-product inventory allocations.
        performance: Per-platform performance metrics.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        total_errors = sum(
            len(s.get("errors", [])) for s in sync_status
        )

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "sync_status": copy.deepcopy(sync_status),
            "price_adjustments_count": len(price_adjustments),
            "inventory_allocation_count": len(inventory_allocation),
            "performance": copy.deepcopy(performance),
            "total_sync_errors": total_errors,
            "platforms": [s.get("platform", "") for s in sync_status],
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

def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
