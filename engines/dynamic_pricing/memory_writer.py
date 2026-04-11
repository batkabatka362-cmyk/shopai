"""Dynamic Pricing Engine — memory writer.

Persists pricing change decisions to disk for future reference
and 24-hour change tracking.

1 file = 1 job: write pricing change records only.
"""
from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any

_MEMORY_DIR = os.path.join(os.path.dirname(__file__), ".memory")


def write_pricing_change(
    product_id: str,
    current_price: float,
    new_price: float,
    change_pct: float,
    reason: str,
    approved: bool,
    estimated_revenue_change: float = 0.0,
) -> dict[str, Any]:
    """Write a pricing change record to memory.

    Args:
        product_id: Product identifier.
        current_price: Price before adjustment.
        new_price: Adjusted price.
        change_pct: Percentage change.
        reason: Human-readable reason for the change.
        approved: Whether the change was validated/approved.
        estimated_revenue_change: Projected revenue impact.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "product_id": str(product_id),
            "current_price": round(float(current_price), 2),
            "new_price": round(float(new_price), 2),
            "change_pct": round(float(change_pct), 2),
            "reason": str(reason),
            "approved": bool(approved),
            "estimated_revenue_change": round(float(estimated_revenue_change), 2),
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


def _ensure_memory_dir() -> None:
    """Create the memory directory if it doesn't exist."""
    os.makedirs(_MEMORY_DIR, exist_ok=True)
