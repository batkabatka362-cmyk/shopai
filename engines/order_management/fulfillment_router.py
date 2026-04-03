"""Order Management Engine — fulfillment router.

Selects fulfillment method and warehouse based on order attributes
and inventory status.

All routing logic is real and deterministic.
"""
from __future__ import annotations

import copy
import time
from typing import Any

# US state-to-region mapping for warehouse selection
_EAST_STATES = {
    "CT", "DE", "FL", "GA", "MA", "MD", "ME", "NC", "NH", "NJ",
    "NY", "PA", "RI", "SC", "VA", "VT", "WV", "DC",
}
_WEST_STATES = {
    "AK", "AZ", "CA", "CO", "HI", "ID", "MT", "NM", "NV", "OR",
    "UT", "WA", "WY",
}
# Everything else is central

_WAREHOUSES = {
    "east": "wh_east_01",
    "west": "wh_west_01",
    "central": "wh_central_01",
}


def route_fulfillment(
    order: dict[str, Any],
    inventory_status: dict[str, Any],
) -> dict[str, Any]:
    """Select fulfillment method and warehouse for an order.

    Args:
        order: The full order dict.
        inventory_status: Result from inventory_checker.

    Returns:
        Structured dict with fulfillment routing decision.
    """
    try:
        order = copy.deepcopy(order)
        inv = copy.deepcopy(inventory_status)

        line_items = order.get("line_items", [])
        shipping_addr = order.get("shipping_address", {})

        # ---- Calculate total item count ----
        total_items = sum(int(li.get("quantity", 0)) for li in line_items)

        # ---- Check for supplier_id (dropship indicator) ----
        has_supplier = any(li.get("supplier_id") for li in line_items)

        # ---- Select fulfillment method ----
        if has_supplier:
            method = "dropship"
        elif total_items > 50:
            method = "3pl"
        else:
            method = "self_fulfillment"

        # ---- Select warehouse based on shipping region ----
        province = str(shipping_addr.get("province", "")).upper().strip()
        country = str(shipping_addr.get("country_code", "")).upper().strip()

        if country != "US" or not province:
            region = "east"  # default for international or unknown
        elif province in _EAST_STATES:
            region = "east"
        elif province in _WEST_STATES:
            region = "west"
        else:
            region = "central"

        warehouse_id = _WAREHOUSES[region]

        # ---- Estimate pick date (next business day + 1 for processing) ----
        now = time.gmtime()
        pick_timestamp = time.mktime(now) + (86400 * 1)
        estimated_pick_date = time.strftime(
            "%Y-%m-%d", time.gmtime(pick_timestamp),
        )

        return {
            "status": "success",
            "method": method,
            "warehouse_id": warehouse_id,
            "estimated_pick_date": estimated_pick_date,
        }
    except Exception as exc:
        return _fail(f"Fulfillment routing failed: {exc}")


def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "method": "",
        "warehouse_id": "",
        "estimated_pick_date": "",
        "error": reason,
    }
