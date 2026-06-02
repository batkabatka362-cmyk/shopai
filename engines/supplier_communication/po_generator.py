"""Supplier Communication Engine — PO generator.

Generates purchase orders by grouping reorder items by supplier,
calculating totals, and assigning PO identifiers with estimated
delivery dates based on supplier lead times.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any


# W962-63: counter race fix. Bare `_PO_COUNTER += 1` is NOT
# atomic in Python (separate LOAD, ADD, STORE bytecodes). Two
# concurrent generate_purchase_orders calls could read the
# same _PO_COUNTER value + emit colliding PO ids (PO-YYYYMMDD-
# 0001 twice). Lock the increment.
_PO_COUNTER = 0
_PO_LOCK = threading.Lock()


def _next_po_id() -> str:
    """Generate a sequential PO identifier."""
    global _PO_COUNTER
    with _PO_LOCK:
        _PO_COUNTER += 1
        n = _PO_COUNTER
    date_str = time.strftime("%Y%m%d", time.gmtime())
    return f"PO-{date_str}-{n:04d}"


def generate_purchase_orders(
    reorder_plan: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate purchase orders from the reorder plan.

    Args:
        reorder_plan: List of ReorderItem dicts.
        suppliers: List of SupplierRecord dicts for lead time / min order.

    Returns:
        Structured dict with generated purchase orders.
    """
    try:
        items = copy.deepcopy(reorder_plan)
        supplier_map: dict[str, dict[str, Any]] = {}
        for s in suppliers:
            sid = str(s.get("supplier_id", ""))
            supplier_map[sid] = s

        # Group items by supplier
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            sid = str(item.get("supplier_id", "unknown"))
            groups.setdefault(sid, []).append(item)

        purchase_orders: list[dict[str, Any]] = []

        for sid, group_items in groups.items():
            supplier = supplier_map.get(sid, {})
            supplier_name = str(supplier.get("name", sid))
            lead_time = int(supplier.get("lead_time_days", 14))
            min_order = float(supplier.get("min_order_value", 0.0))

            po_items: list[dict[str, Any]] = []
            po_total = 0.0

            for item in group_items:
                qty = int(item.get("quantity", 0))
                unit_cost = float(item.get("unit_cost", 0.0))
                line_total = round(qty * unit_cost, 2)
                po_total += line_total

                po_items.append({
                    "product_id": str(item.get("product_id", "")),
                    "title": str(item.get("title", "")),
                    "quantity": qty,
                    "unit_cost": unit_cost,
                    "line_total": line_total,
                })

            # Check minimum order value
            if po_total < min_order:
                status = "below_minimum"
            else:
                status = "ready"

            # Calculate estimated delivery date
            delivery_ts = time.time() + (lead_time * 86400)
            delivery_date = time.strftime(
                "%Y-%m-%d", time.gmtime(delivery_ts),
            )

            purchase_orders.append({
                "po_id": _next_po_id(),
                "supplier_id": sid,
                "supplier_name": supplier_name,
                "items": po_items,
                "total": round(po_total, 2),
                "status": status,
                "delivery_date": delivery_date,
            })

        return {
            "status": "success",
            "purchase_orders": purchase_orders,
        }
    except Exception as exc:
        return {
            "status": "error",
            "purchase_orders": [],
            "error": f"PO generation failed: {exc}",
        }
