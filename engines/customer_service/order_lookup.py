"""Customer Service Engine — order lookup.

Reads order data from the order_management engine's .memory directory
to find and return order details for a given order ID.

All logic is real file reading and matching. No faking.
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from typing import Any


_ORDER_MEMORY_DIR = os.path.join(
    os.path.dirname(__file__), "..", "order_management", ".memory",
)


def lookup_order(
    order_id: str,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """Look up an order by ID, optionally scoped to a customer.

    Args:
        order_id: Order identifier (e.g. "ord_5001").
        customer_id: Optional customer ID to verify ownership.

    Returns:
        Structured dict with order data or not-found.
    """
    try:
        if not order_id or not isinstance(order_id, str):
            return _fail("order_id must be a non-empty string")

        normalised = _normalise_order_id(order_id)

        records = _load_order_records()
        match = _find_order(records, normalised, customer_id)

        if match is None:
            return {
                "status": "success",
                "found": False,
                "order": None,
            }

        order_info = _build_order_info(match)

        return {
            "status": "success",
            "found": True,
            "order": order_info,
        }
    except Exception as exc:
        return _fail(f"Order lookup failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_order_id(raw: str) -> str:
    """Normalise order ID formats: '#5001' -> 'ord_5001', etc."""
    cleaned = raw.strip().lstrip("#")
    if cleaned.startswith("ord_"):
        return cleaned
    if cleaned.isdigit():
        return f"ord_{cleaned}"
    return f"ord_{cleaned}"


def _load_order_records() -> list[dict[str, Any]]:
    """Load all order records from the order_management memory dir."""
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


def _find_order(
    records: list[dict[str, Any]],
    order_id: str,
    customer_id: str | None,
) -> dict[str, Any] | None:
    """Find a record matching the given order_id (and optionally customer_id)."""
    for record in records:
        rec_order_id = str(record.get("order_id", ""))
        if rec_order_id != order_id:
            continue
        if customer_id and str(record.get("customer_id", "")) != customer_id:
            continue
        return copy.deepcopy(record)
    return None


def _build_order_info(record: dict[str, Any]) -> dict[str, Any]:
    """Build a clean order info dict from a raw order record."""
    order_id = str(record.get("order_id", ""))
    status = str(record.get("status", "unknown"))

    # Tracking info
    tracking_block = record.get("tracking", {})
    tracking_number = str(tracking_block.get("carrier_tracking_number", ""))
    shipping_block = record.get("shipping", {})
    carrier = str(shipping_block.get("carrier", ""))
    estimated_delivery = str(shipping_block.get("estimated_delivery", ""))

    # Late calculation
    is_late = False
    days_late = 0
    if estimated_delivery:
        try:
            est_dt = datetime.strptime(estimated_delivery, "%Y-%m-%d").replace(
                tzinfo=timezone.utc,
            )
            now = datetime.now(timezone.utc)
            delta = (now - est_dt).days
            if delta > 0 and status not in ("delivered", "cancelled"):
                is_late = True
                days_late = delta
        except (ValueError, TypeError):
            pass

    return {
        "id": order_id,
        "status": status,
        "tracking_number": tracking_number,
        "carrier": carrier,
        "estimated_delivery": estimated_delivery,
        "is_late": is_late,
        "days_late": days_late,
    }


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardised error result."""
    return {
        "status": "error",
        "found": False,
        "order": None,
        "error": reason,
    }
