"""Order Management Engine — notification dispatcher.

Builds and dispatches notifications based on order status changes.
Generates email subject lines and preview bodies.

No actual email sending — builds the notification payload for downstream.
"""
from __future__ import annotations

import copy
from typing import Any

# Status-to-notification-type mapping
_STATUS_NOTIFICATION_MAP = {
    "confirmed": "order_confirmation",
    "shipped": "shipping_notification",
    "delivered": "delivery_confirmation",
    "cancelled": "cancellation_notice",
    "on_hold": "order_on_hold",
    "processing": "processing_update",
}

# Subject line templates
_SUBJECT_TEMPLATES = {
    "order_confirmation": "Order {order_id} confirmed — thank you for your purchase!",
    "shipping_notification": "Your order {order_id} has shipped!",
    "delivery_confirmation": "Your order {order_id} has been delivered",
    "cancellation_notice": "Order {order_id} has been cancelled",
    "order_on_hold": "Update on your order {order_id}",
    "processing_update": "Your order {order_id} is being processed",
}

# Body preview templates
_BODY_TEMPLATES = {
    "order_confirmation": (
        "Hi {first_name}, we've received your order {order_id} "
        "for {total_price}. We'll notify you when it ships."
    ),
    "shipping_notification": (
        "Great news, {first_name}! Your order {order_id} is on its way. "
        "Track your package: {tracking_url}"
    ),
    "delivery_confirmation": (
        "Hi {first_name}, your order {order_id} has been delivered. "
        "We hope you enjoy your purchase!"
    ),
    "cancellation_notice": (
        "Hi {first_name}, your order {order_id} has been cancelled. "
        "If you have questions, please contact support."
    ),
    "order_on_hold": (
        "Hi {first_name}, your order {order_id} is currently on hold. "
        "We'll update you when there's a change."
    ),
    "processing_update": (
        "Hi {first_name}, your order {order_id} is now being processed "
        "and will ship soon."
    ),
}


def dispatch_notification(
    order: dict[str, Any],
    order_status: str,
    tracking: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and dispatch a notification for an order status change.

    Args:
        order: The full order dict.
        order_status: The current order status triggering the notification.
        tracking: Optional tracking result dict.

    Returns:
        Structured dict with notification details.
    """
    try:
        order = copy.deepcopy(order)
        tracking = copy.deepcopy(tracking) if tracking else {}

        order_id = str(order.get("id", "unknown"))
        email = str(order.get("email", ""))
        total_price = order.get("total_price", 0)
        currency = str(order.get("currency", "USD"))
        shipping_addr = order.get("shipping_address", {})
        first_name = str(shipping_addr.get("first_name", "Customer"))
        tracking_url = tracking.get("tracking_url", "")

        # ---- Determine notification type ----
        notification_type = _STATUS_NOTIFICATION_MAP.get(
            order_status, "status_update",
        )

        # ---- Build subject ----
        subject_template = _SUBJECT_TEMPLATES.get(
            notification_type,
            "Update on your order {order_id}",
        )
        subject = subject_template.format(order_id=order_id)

        # ---- Build body preview ----
        body_template = _BODY_TEMPLATES.get(
            notification_type,
            "Hi {first_name}, there's an update on your order {order_id}.",
        )
        price_str = f"{currency} {total_price}"
        body_preview = body_template.format(
            first_name=first_name,
            order_id=order_id,
            total_price=price_str,
            tracking_url=tracking_url or "N/A",
        )

        # ---- Determine channels ----
        email_sent = bool(email)
        sms_sent = notification_type in ("shipping_notification", "delivery_confirmation")

        return {
            "status": "success",
            "notification_type": notification_type,
            "subject": subject,
            "body_preview": body_preview,
            "email_sent": email_sent,
            "sms_sent": sms_sent,
        }
    except Exception as exc:
        return _fail(f"Notification dispatch failed: {exc}")


def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "notification_type": "",
        "subject": "",
        "body_preview": "",
        "email_sent": False,
        "sms_sent": False,
        "error": reason,
    }
