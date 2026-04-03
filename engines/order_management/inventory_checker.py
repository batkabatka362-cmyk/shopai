"""Order Management Engine — inventory checker.

Checks inventory availability for each line item and reserves units.
Uses a simulated stock lookup (in production, would query inventory service).

All logic is real and deterministic.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any

_DEFAULT_WAREHOUSE = "wh_east_01"


def check_inventory(
    line_items: list[dict[str, Any]],
    warehouse_id: str | None = None,
) -> dict[str, Any]:
    """Check inventory availability for all line items.

    Args:
        line_items: List of LineItem dicts from the order.
        warehouse_id: Optional specific warehouse to check.

    Returns:
        Structured dict with inventory check results.
    """
    try:
        items = copy.deepcopy(line_items)
        warehouse = warehouse_id or _DEFAULT_WAREHOUSE

        reservations: list[dict[str, Any]] = []
        shortages: list[dict[str, Any]] = []
        all_in_stock = True

        for item in items:
            sku = str(item.get("sku", item.get("product_id", "unknown")))
            requested_qty = int(item.get("quantity", 0))

            # Simulated stock: derive available quantity from SKU hash
            # This gives a deterministic but varied stock level per SKU
            available = _simulate_stock_level(sku)

            if requested_qty <= available:
                reservations.append({
                    "sku": sku,
                    "quantity": requested_qty,
                    "reserved": True,
                    "warehouse": warehouse,
                })
            else:
                all_in_stock = False
                reservations.append({
                    "sku": sku,
                    "quantity": requested_qty,
                    "reserved": False,
                    "warehouse": warehouse,
                })
                shortages.append({
                    "sku": sku,
                    "requested": requested_qty,
                    "available": available,
                })

        return {
            "status": "success",
            "all_in_stock": all_in_stock,
            "reservations": reservations,
            "shortages": shortages,
        }
    except Exception as exc:
        return _fail(f"Inventory check failed: {exc}")


def _simulate_stock_level(sku: str) -> int:
    """Derive a deterministic simulated stock level from a SKU.

    Uses a hash to produce a consistent stock number for any given SKU.
    Range: 5 to 500 units.
    """
    h = hashlib.md5(sku.encode()).hexdigest()
    num = int(h[:8], 16)
    return 5 + (num % 496)


def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "all_in_stock": False,
        "reservations": [],
        "shortages": [],
        "error": reason,
    }
