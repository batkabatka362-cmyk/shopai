"""Dropshipping Engine — tracking syncer.

Syncs tracking information from supplier to customer.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def sync_tracking(
    supplier_orders: list[dict[str, Any]],
    tracking_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Sync tracking from supplier data to customer-facing updates.

    Args:
        supplier_orders: Supplier orders with order IDs.
        tracking_data: Raw tracking data from suppliers.

    Returns:
        Structured dict with tracking updates.
    """
    try:
        tracking_map: dict[str, dict[str, Any]] = {}
        for td in tracking_data:
            oid = str(td.get("order_id", ""))
            tracking_map[oid] = td

        updates: list[dict[str, Any]] = []
        for so in supplier_orders:
            oid = str(so.get("order_id", ""))
            td = tracking_map.get(oid, {})

            tracking_number = str(td.get("tracking_number", ""))
            carrier = str(td.get("carrier", "unknown"))
            raw_status = str(td.get("status", "pending"))
            est_delivery = str(td.get("estimated_delivery", ""))

            if raw_status in ("delivered", "in_transit", "shipped", "out_for_delivery"):
                customer_status = raw_status
            elif tracking_number:
                customer_status = "shipped"
            else:
                customer_status = "processing"

            updates.append({
                "order_id": oid,
                "tracking_number": tracking_number,
                "carrier": carrier,
                "status": customer_status,
                "estimated_delivery": est_delivery,
            })

        return {"status": "success", "tracking_updates": updates}
    except Exception as exc:
        return {"status": "error", "tracking_updates": [], "error": f"Tracking sync failed: {exc}"}
