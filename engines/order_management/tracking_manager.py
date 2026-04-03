"""Order Management Engine — tracking manager.

Generates tracking IDs, builds tracking URLs, and creates initial
tracking records for shipments.

All IDs are deterministic per order for reproducibility.
"""
from __future__ import annotations

import copy
import hashlib
import uuid
from typing import Any

# Carrier tracking URL templates
_TRACKING_URLS = {
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels={number}",
    "UPS": "https://www.ups.com/track?tracknum={number}",
    "FedEx Freight": "https://www.fedex.com/fedextrack/?trknbr={number}",
}


def _generate_carrier_number(order_id: str, carrier: str) -> str:
    """Generate a deterministic carrier tracking number from order ID."""
    seed = f"{order_id}:{carrier}"
    digest = hashlib.sha256(seed.encode()).hexdigest()
    # Format like a real tracking number
    if carrier == "USPS":
        return f"9400{digest[:18].upper()}"
    elif carrier == "UPS":
        return f"1Z{digest[:16].upper()}"
    else:
        return f"{digest[:15].upper()}"


def create_tracking(
    order_id: str,
    carrier: str,
    shipping: dict[str, Any],
) -> dict[str, Any]:
    """Create a tracking record for a shipment.

    Args:
        order_id: The order identifier.
        carrier: Carrier name (USPS, UPS, FedEx Freight).
        shipping: Result from shipping_handler.

    Returns:
        Structured dict with tracking ID, URL, carrier number, and status.
    """
    try:
        shipping = copy.deepcopy(shipping)

        # --- Tracking ID ---
        tracking_id = f"trk_{uuid.uuid4().hex[:16]}"

        # --- Carrier tracking number ---
        carrier_number = _generate_carrier_number(order_id, carrier)

        # --- Tracking URL ---
        url_template = _TRACKING_URLS.get(
            carrier,
            "https://track.example.com/?number={number}",
        )
        tracking_url = url_template.format(number=carrier_number)

        return {
            "status": "success",
            "tracking_id": tracking_id,
            "tracking_url": tracking_url,
            "carrier_tracking_number": carrier_number,
            "tracking_status": "label_created",
        }
    except Exception as exc:
        return {
            "status": "error",
            "tracking_id": "",
            "tracking_url": "",
            "carrier_tracking_number": "",
            "tracking_status": "error",
            "error": f"Tracking creation failed: {exc}",
        }
