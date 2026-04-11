"""Supplier Communication Engine — tracking monitor.

Monitors shipment tracking from suppliers. Checks expected delivery
dates against current date, flags delays, and produces status updates.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
from typing import Any


def monitor_tracking(
    purchase_orders: list[dict[str, Any]],
    inventory_status: list[dict[str, Any]],
) -> dict[str, Any]:
    """Monitor tracking status for all purchase orders.

    Args:
        purchase_orders: List of PurchaseOrder dicts from po_generator.
        inventory_status: Current inventory status for urgency context.

    Returns:
        Structured dict with tracking updates.
    """
    try:
        po_items = copy.deepcopy(purchase_orders)

        # Build urgency map from inventory status
        urgency_map: dict[str, str] = {}
        for inv in inventory_status:
            pid = str(inv.get("product_id", ""))
            status = str(inv.get("status", "healthy"))
            urgency_map[pid] = status

        current_date = time.strftime("%Y-%m-%d", time.gmtime())
        tracking_updates: list[dict[str, Any]] = []

        for po in po_items:
            po_id = str(po.get("po_id", ""))
            sid = str(po.get("supplier_id", ""))
            delivery_date = str(po.get("delivery_date", ""))
            po_status = str(po.get("status", "ready"))
            items = po.get("items", [])

            # Check if any items are critical in inventory
            has_critical = False
            for item in items:
                pid = str(item.get("product_id", ""))
                inv_status = urgency_map.get(pid, "healthy")
                if inv_status in ("critical", "low"):
                    has_critical = True
                    break

            # Determine tracking status
            if po_status == "below_minimum":
                track_status = "pending_confirmation"
                notes = "Order below supplier minimum — awaiting confirmation"
            elif delivery_date < current_date:
                track_status = "delayed"
                notes = f"Expected delivery {delivery_date} has passed — follow up required"
            elif has_critical:
                track_status = "urgent"
                notes = "Contains critical inventory items — expedite if possible"
            else:
                track_status = "on_track"
                notes = f"Expected delivery on {delivery_date}"

            tracking_updates.append({
                "po_id": po_id,
                "supplier_id": sid,
                "status": track_status,
                "expected_delivery": delivery_date,
                "notes": notes,
            })

        return {
            "status": "success",
            "tracking_updates": tracking_updates,
        }
    except Exception as exc:
        return {
            "status": "error",
            "tracking_updates": [],
            "error": f"Tracking monitoring failed: {exc}",
        }
