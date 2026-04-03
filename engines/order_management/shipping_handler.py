"""Order Management Engine — shipping handler.

Selects carrier, service level, and estimates shipping cost based on
order weight and destination.

All calculations are deterministic and rule-based.
"""
from __future__ import annotations

import copy
import time
from typing import Any

# Carrier selection thresholds (total weight in grams)
_USPS_MAX_GRAMS = 907     # ~2 lbs
_UPS_MAX_GRAMS = 22680    # ~50 lbs
# Above UPS_MAX = freight

# Rate per gram by carrier (USD)
_RATES = {
    "USPS": 0.005,
    "UPS": 0.003,
    "FedEx Freight": 0.002,
}

# Service level transit days
_SERVICE_DAYS = {
    "standard": {"min": 5, "max": 7},
    "express": {"min": 2, "max": 3},
    "overnight": {"min": 1, "max": 1},
}


def _compute_total_weight(order: dict[str, Any]) -> int:
    """Sum weight in grams across all line items."""
    total = 0
    for item in order.get("line_items", []):
        grams = int(item.get("grams", 0))
        qty = int(item.get("quantity", 1))
        total += grams * qty
    return total


def _select_service_level(order: dict[str, Any]) -> str:
    """Determine service level from order metadata or default to standard."""
    # Check for explicit service level request
    requested = str(order.get("shipping_service", "")).lower()
    if requested in _SERVICE_DAYS:
        return requested
    # Default: orders over $200 get express, otherwise standard
    total = float(order.get("total_price", 0))
    if total >= 200:
        return "express"
    return "standard"


def handle_shipping(
    order: dict[str, Any],
    fulfillment: dict[str, Any],
) -> dict[str, Any]:
    """Select carrier and estimate shipping cost for the order.

    Args:
        order: Order dict with line items (including grams).
        fulfillment: Result from fulfillment_router.

    Returns:
        Structured dict with carrier, service, cost, and delivery estimate.
    """
    try:
        order = copy.deepcopy(order)
        fulfillment = copy.deepcopy(fulfillment)

        total_weight = _compute_total_weight(order)

        # --- Carrier selection by weight ---
        if total_weight <= _USPS_MAX_GRAMS:
            carrier = "USPS"
        elif total_weight <= _UPS_MAX_GRAMS:
            carrier = "UPS"
        else:
            carrier = "FedEx Freight"

        # --- Service level ---
        service = _select_service_level(order)
        transit = _SERVICE_DAYS.get(service, _SERVICE_DAYS["standard"])

        # --- Cost estimate ---
        rate = _RATES.get(carrier, 0.003)
        base_cost = total_weight * rate

        # Service multiplier
        if service == "express":
            base_cost *= 1.5
        elif service == "overnight":
            base_cost *= 3.0

        # Minimum shipping cost
        estimated_cost = round(max(base_cost, 4.99), 2)

        # --- Estimated delivery date ---
        max_transit_days = transit["max"]
        pick_date_str = fulfillment.get("estimated_pick_date", "")
        if pick_date_str:
            try:
                pick_ts = time.mktime(time.strptime(pick_date_str, "%Y-%m-%d"))
                delivery_ts = pick_ts + (max_transit_days * 86400)
                estimated_delivery = time.strftime(
                    "%Y-%m-%d", time.gmtime(delivery_ts),
                )
            except (ValueError, OverflowError):
                delivery_ts = time.time() + (max_transit_days * 86400)
                estimated_delivery = time.strftime(
                    "%Y-%m-%d", time.gmtime(delivery_ts),
                )
        else:
            delivery_ts = time.time() + (max_transit_days * 86400)
            estimated_delivery = time.strftime(
                "%Y-%m-%d", time.gmtime(delivery_ts),
            )

        return {
            "status": "success",
            "carrier": carrier,
            "service": service,
            "estimated_cost": estimated_cost,
            "estimated_delivery": estimated_delivery,
            "total_weight_grams": total_weight,
        }
    except Exception as exc:
        return {
            "status": "error",
            "carrier": "",
            "service": "",
            "estimated_cost": 0.0,
            "estimated_delivery": "",
            "error": f"Shipping handling failed: {exc}",
        }
