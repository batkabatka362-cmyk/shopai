"""Order Management Engine — inventory checker.

Checks stock availability for each line item and reserves units.
Uses simulated stock levels (in production, this would call a real
inventory service or database).

All logic is deterministic and real.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any

# Simulated stock levels — in production this queries the inventory DB.
# We derive a deterministic stock level from the SKU so results are
# reproducible across runs.
_DEFAULT_WAREHOUSE = "wh_east_01"


def _simulated_stock(sku: str) -> int:
    """Derive a deterministic stock quantity from SKU string.

    Uses a hash to produce a stable number between 0 and 200.
    """
    digest = hashlib.md5(sku.encode()).hexdigest()
    return int(digest[:4], 16) % 201  # 0–200 units


def check_inventory(
    line_items: list[dict[str, Any]],
    warehouse_id: str | None = None,
) -> dict[str, Any]:
    """Check inventory availability for each line item.

    Args:
        line_items: List of LineItem dicts.
        warehouse_id: Optional warehouse to check. Defaults to east warehouse.

    Returns:
        Structured dict with reservation status, reservations, and shortages.
    """
    try:
        items = copy.deepcopy(line_items)
        wh = warehouse_id or _DEFAULT_WAREHOUSE

        reservations: list[dict[str, Any]] = []
        shortages: list[dict[str, Any]] = []
        all_in_stock = True

        for item in items:
            sku = str(item.get("sku", item.get("product_id", "unknown")))
            requested_qty = int(item.get("quantity", 1))
            available = _simulated_stock(sku)

            if available >= requested_qty:
                reservations.append({
                    "sku": sku,
                    "quantity": requested_qty,
                    "reserved": True,
                    "warehouse": wh,
                    "available_before": available,
                    "available_after": available - requested_qty,
                })
            else:
                all_in_stock = False
                # Reserve what we can
                reserved_qty = min(available, requested_qty)
                reservations.append({
                    "sku": sku,
                    "quantity": reserved_qty,
                    "reserved": reserved_qty > 0,
                    "warehouse": wh,
                    "available_before": available,
                    "available_after": max(available - reserved_qty, 0),
                })
                shortages.append({
                    "sku": sku,
                    "requested": requested_qty,
                    "available": available,
                    "shortage": requested_qty - available,
                })

        return {
            "status": "success",
            "all_in_stock": all_in_stock,
            "reservations": reservations,
            "shortages": shortages,
        }
    except Exception as exc:
        return {
            "status": "error",
            "all_in_stock": False,
            "reservations": [],
            "shortages": [],
            "error": f"Inventory check failed: {exc}",
        }
