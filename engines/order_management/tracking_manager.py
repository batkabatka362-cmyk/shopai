"""Order Management Engine — tracking manager.

Generates tracking IDs and builds tracking URLs for shipments.

All IDs are deterministic where possible. No external API calls.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

_TRACKING_URL_TEMPLATES = {
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels={number}",
    "UPS": "https://www.ups.com/track?tracknum={number}",
    "FedEx": "https://www.fedex.com/fedextrack/?trknbr={number}",
    "freight": "https://freight.example.com/track/{number}",
}


def create_tracking(
    order_id: str,
    carrier: str,
    shipping: dict[str, Any],
) -> dict[str, Any]:
    """Create tracking record for a shipment.

    Args:
        order_id: The order ID.
        carrier: Selected carrier name.
        shipping: Result from shipping_handler.

    Returns:
        Structured dict with tracking details.
    """
    try:
        shipping = copy.deepcopy(shipping)

        # ---- Generate tracking ID (internal) ----
        tracking_id = f"trk_{uuid.uuid4().hex}"

        # ---- Generate carrier tracking number ----
        # Deterministic from order_id for consistency
        carrier_hex = uuid.uuid5(uuid.NAMESPACE_DNS, f"{order_id}.{carrier}").hex
        carrier_tracking_number = carrier_hex[:20].upper()

        # ---- Build tracking URL ----
        url_template = _TRACKING_URL_TEMPLATES.get(
            carrier,
            "https://track.example.com/{number}",
        )
        tracking_url = url_template.format(number=carrier_tracking_number)

        return {
            "status": "success",
            "tracking_id": tracking_id,
            "tracking_url": tracking_url,
            "carrier_tracking_number": carrier_tracking_number,
            "tracking_status": "label_created",
        }
    except Exception as exc:
        return _fail(f"Tracking creation failed: {exc}")


def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "tracking_id": "",
        "tracking_url": "",
        "carrier_tracking_number": "",
        "tracking_status": "failed",
        "error": reason,
    }
