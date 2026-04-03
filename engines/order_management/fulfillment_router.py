"""Order Management Engine — fulfillment router.

Selects fulfillment method (self, 3PL, dropship) and warehouse based on
order characteristics and shipping destination.

All routing logic is deterministic and rule-based.
"""
from __future__ import annotations

import copy
import time
from typing import Any

# US state → region mapping for warehouse selection
_EAST_STATES = {
    "CT", "DE", "FL", "GA", "MA", "MD", "ME", "NC", "NH", "NJ",
    "NY", "PA", "RI", "SC", "VA", "VT", "WV", "DC",
}
_WEST_STATES = {
    "AK", "AZ", "CA", "CO", "HI", "ID", "MT", "NM", "NV", "OR",
    "UT", "WA", "WY",
}
# Everything else is central

_WAREHOUSE_MAP = {
    "east": "wh_east_01",
    "west": "wh_west_01",
    "central": "wh_central_01",
}


def _get_region(province: str) -> str:
    """Map a US state/province code to a fulfillment region."""
    code = province.upper().strip()
    if code in _EAST_STATES:
        return "east"
    if code in _WEST_STATES:
        return "west"
    return "central"


def _total_item_count(order: dict[str, Any]) -> int:
    """Sum quantities across all line items."""
    total = 0
    for item in order.get("line_items", []):
        total += int(item.get("quantity", 1))
    return total


def route_fulfillment(
    order: dict[str, Any],
    inventory_status: dict[str, Any],
) -> dict[str, Any]:
    """Select fulfillment method and warehouse for the order.

    Args:
        order: Order dict with line items and shipping address.
        inventory_status: Result from inventory_checker.

    Returns:
        Structured dict with fulfillment method, warehouse, and pick date.
    """
    try:
        order = copy.deepcopy(order)
        inv = copy.deepcopy(inventory_status)

        # --- Determine fulfillment method ---
        total_items = _total_item_count(order)

        # Check if any line item has a supplier_id (dropship)
        has_supplier = any(
            item.get("supplier_id")
            for item in order.get("line_items", [])
        )

        if has_supplier:
            method = "dropship"
        elif total_items > 50:
            method = "3pl"
        else:
            method = "self_fulfillment"

        # --- Select warehouse based on shipping region ---
        shipping_addr = order.get("shipping_address", {})
        province = str(shipping_addr.get("province", ""))
        country_code = str(shipping_addr.get("country_code", "US")).upper()

        if country_code == "US" and province:
            region = _get_region(province)
        else:
            # Default to east for non-US or unknown
            region = "east"

        warehouse_id = _WAREHOUSE_MAP.get(region, "wh_east_01")

        # --- Estimate pick date (1 business day for self, 2 for 3PL, varies for dropship) ---
        if method == "self_fulfillment":
            pick_days = 1
        elif method == "3pl":
            pick_days = 2
        else:
            pick_days = 3

        # Simple estimated pick date: today + pick_days
        pick_timestamp = time.time() + (pick_days * 86400)
        estimated_pick_date = time.strftime(
            "%Y-%m-%d", time.gmtime(pick_timestamp),
        )

        return {
            "status": "success",
            "method": method,
            "warehouse_id": warehouse_id,
            "estimated_pick_date": estimated_pick_date,
            "region": region,
            "total_items": total_items,
        }
    except Exception as exc:
        return {
            "status": "error",
            "method": "",
            "warehouse_id": "",
            "estimated_pick_date": "",
            "error": f"Fulfillment routing failed: {exc}",
        }
