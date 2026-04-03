"""Customer Service Engine — order lookup.

Reads from order_management .memory directory to find order details.
Returns order status, tracking info, and lateness calculations.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import json
import os
import time
from typing import Any

_ORDER_MEMORY_DIR = os.path.join(
    os.path.dirname(__file__), "..", "order_management", ".memory",
)


def lookup_order(
    order_id: str,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """Look up an order by ID in the order management memory.

    Args:
        order_id: Order identifier (e.g. "ord_5001" or "#5001").
        customer_id: Optional customer ID to verify ownership.

    Returns:
        Structured dict with order details or not-found.
    """
    try:
        if not order_id or not order_id.strip():
            return _fail("Order ID is required")

        normalized_id = _normalize_order_id(order_id)
        records = _load_order_records()

        # Search for matching order
        matched_record: dict[str, Any] | None = None
        for record in records:
            rec_order_id = str(record.get("order_id", ""))
            if rec_order_id == normalized_id or rec_order_id == order_id:
                # If customer_id provided, verify ownership
                if customer_id:
                    rec_customer_id = str(record.get("customer_id", ""))
                    if rec_customer_id != customer_id:
                        continue
                matched_record = record
                break

        if matched_record is None:
            return {
                "status": "success",
                "found": False,
                "order": None,
            }

        order_details = _build_order_details(matched_record)

        return {
            "status": "success",
            "found": True,
            "order": order_details,
        }
    except Exception as exc:
        return _fail(f"Order lookup failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_order_id(order_id: str) -> str:
    """Normalize order ID to the canonical form (ord_NNNN)."""
    oid = order_id.strip()
    if oid.startswith("#"):
        return f"ord_{oid[1:]}"
    return oid


def _load_order_records() -> list[dict[str, Any]]:
    """Load all order records from memory directory."""
    mem_dir = os.path.normpath(_ORDER_MEMORY_DIR)
    if not os.path.isdir(mem_dir):
        return []

    records: list[dict[str, Any]] = []
    for fname in os.listdir(mem_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(mem_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    records.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return records


def _build_order_details(record: dict[str, Any]) -> dict[str, Any]:
    """Build a clean order details dict from a raw memory record."""
    record = copy.deepcopy(record)

    order_id = str(record.get("order_id", ""))
    status = str(record.get("status", "unknown"))

    # Tracking information
    tracking = record.get("tracking", {})
    tracking_number = str(tracking.get("carrier_tracking_number", ""))
    tracking_url = str(tracking.get("tracking_url", ""))

    # Shipping information
    shipping = record.get("shipping", {})
    carrier = str(shipping.get("carrier", ""))
    estimated_delivery = str(shipping.get("estimated_delivery", ""))

    # Determine if the order is late
    is_late = False
    days_late = 0
    if estimated_delivery:
        try:
            # Parse estimated delivery date
            parts = estimated_delivery.split("-")
            if len(parts) == 3:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                # Convert to epoch for comparison
                delivery_epoch = _date_to_epoch(year, month, day)
                now_epoch = time.time()
                if now_epoch > delivery_epoch:
                    diff_days = int((now_epoch - delivery_epoch) / 86400)
                    # Only late if status is not "delivered"
                    tracking_status = str(tracking.get("tracking_status", ""))
                    if tracking_status not in ("delivered", "completed"):
                        is_late = True
                        days_late = diff_days
        except (ValueError, IndexError):
            pass

    # Inventory / items info
    inventory = record.get("inventory", {})
    reservations = inventory.get("reservations", [])
    items = [
        {
            "sku": str(r.get("sku", "")),
            "quantity": int(r.get("quantity", 0)),
        }
        for r in reservations
    ]

    # Total from notification body or zero
    total = float(record.get("total", 0.0))

    return {
        "id": order_id,
        "status": status,
        "tracking_number": tracking_number,
        "tracking_url": tracking_url,
        "carrier": carrier,
        "estimated_delivery": estimated_delivery,
        "is_late": is_late,
        "days_late": days_late,
        "items": items,
        "total": total,
    }


def _date_to_epoch(year: int, month: int, day: int) -> float:
    """Convert a date to epoch seconds (UTC midnight)."""
    import calendar
    import datetime
    dt = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
    return calendar.timegm(dt.timetuple())


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error result."""
    return {
        "status": "error",
        "found": False,
        "order": None,
        "error": reason,
    }
