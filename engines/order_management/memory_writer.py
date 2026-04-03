"""Order Management Engine — memory writer.

Persists order processing results to disk for future reference.
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


def write_order_record(
    order_id: str,
    customer_id: str,
    status: str,
    fulfillment: dict[str, Any],
    shipping: dict[str, Any],
    tracking: dict[str, Any],
    fraud_screen: dict[str, Any] | None = None,
    inventory: dict[str, Any] | None = None,
    notification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write an order processing record to memory.

    Args:
        order_id: The order ID.
        customer_id: The customer ID.
        status: Final order status.
        fulfillment: Fulfillment routing result.
        shipping: Shipping handler result.
        tracking: Tracking manager result.
        fraud_screen: Optional fraud screening result.
        inventory: Optional inventory check result.
        notification: Optional notification result.

    Returns:
        Structured dict confirming the write.
    """
    try:
        record_id = uuid.uuid4().hex[:12]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": timestamp,
            "order_id": order_id,
            "customer_id": customer_id,
            "status": status,
            "fulfillment": copy.deepcopy(fulfillment),
            "shipping": copy.deepcopy(shipping),
            "tracking": copy.deepcopy(tracking),
        }

        if fraud_screen:
            record["fraud_screen"] = copy.deepcopy(fraud_screen)
        if inventory:
            record["inventory"] = copy.deepcopy(inventory)
        if notification:
            record["notification"] = copy.deepcopy(notification)

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
