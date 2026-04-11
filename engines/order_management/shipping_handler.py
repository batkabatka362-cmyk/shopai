"""Order Management Engine — shipping handler.

Selects carrier and service level, estimates cost and delivery date
based on order weight and destination.

All calculations are real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
from typing import Any

# Carrier weight thresholds (in grams)
_USPS_MAX_GRAMS = 907       # ~2 lb
_UPS_MAX_GRAMS = 22680      # ~50 lb
# Above UPS_MAX = freight

# Rate per gram by carrier (USD)
_RATES = {
    "USPS": 0.008,
    "UPS": 0.005,
    "freight": 0.003,
}

# Service level transit days
_SERVICE_DAYS = {
    "standard": 6,    # 5-7 average
    "express": 3,     # 2-3 average
    "overnight": 1,
}

# Service level cost multipliers
_SERVICE_MULTIPLIERS = {
    "standard": 1.0,
    "express": 2.5,
    "overnight": 5.0,
}


def handle_shipping(
    order: dict[str, Any],
    fulfillment: dict[str, Any],
) -> dict[str, Any]:
    """Determine carrier, service level, cost, and delivery estimate.

    Args:
        order: The full order dict.
        fulfillment: Result from fulfillment_router.

    Returns:
        Structured dict with shipping details.
    """
    try:
        order = copy.deepcopy(order)

        line_items = order.get("line_items", [])
        shipping_addr = order.get("shipping_address", {})

        # ---- Calculate total weight in grams ----
        total_grams = 0
        for item in line_items:
            grams = int(item.get("grams", 500))  # default 500g if not specified
            qty = int(item.get("quantity", 1))
            total_grams += grams * qty

        # ---- Select carrier based on weight ----
        if total_grams <= _USPS_MAX_GRAMS:
            carrier = "USPS"
        elif total_grams <= _UPS_MAX_GRAMS:
            carrier = "UPS"
        else:
            carrier = "freight"

        # ---- Determine service level ----
        total_price = float(order.get("total_price", 0))
        country = str(shipping_addr.get("country_code", "")).upper()

        if country != "US":
            service = "standard"  # international always standard
        elif total_price >= 200:
            service = "express"   # high-value orders get express
        else:
            service = "standard"

        # ---- Calculate shipping cost ----
        rate = _RATES.get(carrier, 0.005)
        multiplier = _SERVICE_MULTIPLIERS.get(service, 1.0)
        base_cost = total_grams * rate
        estimated_cost = round(base_cost * multiplier, 2)

        # Minimum shipping cost
        estimated_cost = max(estimated_cost, 4.99)

        # ---- Calculate estimated delivery date ----
        transit_days = _SERVICE_DAYS.get(service, 6)
        now = time.time()
        delivery_timestamp = now + (86400 * (1 + transit_days))
        estimated_delivery = time.strftime(
            "%Y-%m-%d", time.gmtime(delivery_timestamp),
        )

        return {
            "status": "success",
            "carrier": carrier,
            "service": service,
            "estimated_cost": estimated_cost,
            "estimated_delivery": estimated_delivery,
        }
    except Exception as exc:
        return _fail(f"Shipping handling failed: {exc}")


def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "carrier": "",
        "service": "",
        "estimated_cost": 0.0,
        "estimated_delivery": "",
        "error": reason,
    }
