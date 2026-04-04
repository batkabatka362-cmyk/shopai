"""Supplier Communication Engine — memory writer.

Persists supplier communication decisions to disk for future reference.
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


def write_communication_result(
    purchase_orders: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    tracking_updates: list[dict[str, Any]],
    negotiation_tips: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write a supplier communication result record to memory.

    Args:
        purchase_orders: List of purchase order dicts.
        messages: List of message dicts.
        tracking_updates: List of tracking update dicts.
        negotiation_tips: List of negotiation tip dicts.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        total_po_value = sum(float(po.get("total", 0.0)) for po in purchase_orders)

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "po_count": len(purchase_orders),
            "total_po_value": round(total_po_value, 2),
            "messages_count": len(messages),
            "tracking_count": len(tracking_updates),
            "negotiation_tips_count": len(negotiation_tips),
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
