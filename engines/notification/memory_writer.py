"""Notification Engine — memory writer.

Persists notification decisions to disk for future reference.
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


def write_notification_result(
    notifications: list[dict[str, Any]],
    delivery_status: list[dict[str, Any]],
    opt_out_check: bool,
) -> dict[str, Any]:
    """Write a notification result record to memory.

    Args:
        notifications: List of notification items sent.
        delivery_status: Delivery tracking records.
        opt_out_check: Whether opt-out was validated.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        channels_used = list({n.get("channel", "") for n in notifications})

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "notifications_count": len(notifications),
            "channels_used": channels_used,
            "delivery_statuses": [d.get("status", "") for d in delivery_status],
            "opt_out_check": opt_out_check,
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
