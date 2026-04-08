"""Order Management Engine — inventory checker.

Checks inventory availability for each line item against the
caller-supplied ``stock_levels`` map. There is no local inventory
simulator anymore — an earlier version of this module derived a
"stock level" from ``md5(sku)`` which returned a plausible-looking
number (5–500) that had no relationship to the real warehouse.
Downstream engines treated those fake numbers as truth and made
reservation decisions on them.

When real inventory is unknown the caller should pass an empty
``stock_levels`` dict. This module will then mark every line item
as ``unknown`` (neither reserved nor shortage) so the adapter layer
can query the real source (Shopify Inventory API, NetSuite, etc.)
without this engine silently making up numbers.
"""
from __future__ import annotations

import copy
from typing import Any

_DEFAULT_WAREHOUSE = "wh_east_01"


def check_inventory(
    line_items: list[dict[str, Any]],
    warehouse_id: str | None = None,
    stock_levels: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Check inventory availability for all line items.

    Args:
        line_items: List of LineItem dicts from the order.
        warehouse_id: Optional specific warehouse to check.
        stock_levels: Mapping of ``sku → available units``. When a
            SKU is missing from this map the item is classified as
            ``unknown`` (not reserved, not a shortage) so the
            caller can resolve it via the real inventory adapter.
            Pre-cleanup this parameter did not exist and the module
            silently invented per-SKU stock from an MD5 hash.

    Returns:
        Structured dict with inventory check results. A new
        ``unknown`` list captures items whose stock was not supplied
        in ``stock_levels`` — the caller should treat the value as
        "needs real adapter lookup" rather than "in stock".
    """
    try:
        items = copy.deepcopy(line_items)
        warehouse = warehouse_id or _DEFAULT_WAREHOUSE
        stock_map = dict(stock_levels or {})

        reservations: list[dict[str, Any]] = []
        shortages: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []
        all_in_stock = True

        for item in items:
            sku = str(item.get("sku", item.get("product_id", "unknown")))
            requested_qty = int(item.get("quantity", 0))

            if sku not in stock_map:
                # No fake data — an adapter must resolve this.
                all_in_stock = False
                unknown.append({
                    "sku": sku,
                    "requested": requested_qty,
                    "reason": "stock_not_supplied",
                })
                reservations.append({
                    "sku": sku,
                    "quantity": requested_qty,
                    "reserved": False,
                    "warehouse": warehouse,
                    "reason": "stock_not_supplied",
                })
                continue

            available = int(stock_map[sku])
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
            "unknown": unknown,
        }
    except Exception as exc:
        return _fail(f"Inventory check failed: {exc}")


def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "all_in_stock": False,
        "reservations": [],
        "shortages": [],
        "unknown": [],
        "error": reason,
    }
