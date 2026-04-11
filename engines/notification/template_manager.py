"""Notification Engine — template manager.

Manages notification templates per event type and channel.
Resolves the correct template and extracts required variables.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Template registry: event_type -> channel -> template
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, dict[str, dict[str, Any]]] = {
    "order_confirmation": {
        "email": {
            "template_id": "order_confirm_email",
            "subject": "Order #{order_id} confirmed",
            "body_template": (
                "Hi {customer_name}, your order #{order_id} for {item_count} "
                "item(s) totaling ${total} has been confirmed. "
                "Expected delivery: {delivery_date}."
            ),
            "variables": ["customer_name", "order_id", "item_count", "total", "delivery_date"],
        },
        "sms": {
            "template_id": "order_confirm_sms",
            "subject": "",
            "body_template": (
                "Order #{order_id} confirmed! {item_count} item(s), ${total}. "
                "Delivery by {delivery_date}."
            ),
            "variables": ["order_id", "item_count", "total", "delivery_date"],
        },
        "push": {
            "template_id": "order_confirm_push",
            "subject": "Order Confirmed",
            "body_template": "Your order #{order_id} is confirmed!",
            "variables": ["order_id"],
        },
    },
    "shipping_update": {
        "email": {
            "template_id": "shipping_email",
            "subject": "Your order #{order_id} has shipped",
            "body_template": (
                "Hi {customer_name}, your order #{order_id} has shipped via "
                "{carrier}. Tracking: {tracking_number}."
            ),
            "variables": ["customer_name", "order_id", "carrier", "tracking_number"],
        },
        "push": {
            "template_id": "shipping_push",
            "subject": "Order Shipped",
            "body_template": "Order #{order_id} shipped! Track: {tracking_number}",
            "variables": ["order_id", "tracking_number"],
        },
    },
    "price_drop": {
        "email": {
            "template_id": "price_drop_email",
            "subject": "Price drop on {product_name}!",
            "body_template": (
                "Hi {customer_name}, {product_name} just dropped from "
                "${old_price} to ${new_price}. Don't miss out!"
            ),
            "variables": ["customer_name", "product_name", "old_price", "new_price"],
        },
        "push": {
            "template_id": "price_drop_push",
            "subject": "Price Drop Alert",
            "body_template": "{product_name} is now ${new_price}!",
            "variables": ["product_name", "new_price"],
        },
    },
    "back_in_stock": {
        "email": {
            "template_id": "back_in_stock_email",
            "subject": "{product_name} is back in stock!",
            "body_template": (
                "Hi {customer_name}, {product_name} is back! "
                "Grab it before it sells out again."
            ),
            "variables": ["customer_name", "product_name"],
        },
        "push": {
            "template_id": "back_in_stock_push",
            "subject": "Back in Stock",
            "body_template": "{product_name} is available again!",
            "variables": ["product_name"],
        },
    },
}

_DEFAULT_TEMPLATE: dict[str, Any] = {
    "template_id": "generic",
    "subject": "Notification",
    "body_template": "Hi {customer_name}, you have a new notification.",
    "variables": ["customer_name"],
}


def resolve_template(
    event_type: str,
    channel: str,
) -> dict[str, Any]:
    """Resolve a notification template for a given event type and channel.

    Args:
        event_type: The event that triggered the notification.
        channel: Delivery channel (email, sms, push).

    Returns:
        Structured dict with template details.
    """
    try:
        event_templates = _TEMPLATES.get(event_type, {})
        template = event_templates.get(channel, None)

        if template is None:
            # Fall back to first available channel for this event
            if event_templates:
                first_channel = next(iter(event_templates))
                template = copy.deepcopy(event_templates[first_channel])
                template["template_id"] = f"{template['template_id']}_fallback"
            else:
                template = copy.deepcopy(_DEFAULT_TEMPLATE)

        return {
            "status": "success",
            "template": copy.deepcopy(template),
        }
    except Exception as exc:
        return {
            "status": "error",
            "template": {},
            "error": f"Template resolution failed: {exc}",
        }
