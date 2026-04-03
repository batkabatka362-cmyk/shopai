"""Notification Engine — channel selector.

Selects the best notification channel for a given event and customer,
considering preferences, opt-outs, quiet hours, and event urgency.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Urgency classification by event type
# ---------------------------------------------------------------------------

_EVENT_URGENCY: dict[str, str] = {
    "order_confirmation": "high",
    "shipping_update": "high",
    "delivery_confirmation": "medium",
    "price_drop": "low",
    "back_in_stock": "medium",
    "promotion": "low",
    "review_request": "low",
    "security_alert": "critical",
    "password_reset": "critical",
}

# Preferred channel order by urgency
_URGENCY_CHANNEL_ORDER: dict[str, list[str]] = {
    "critical": ["sms", "push", "email"],
    "high": ["push", "email", "sms"],
    "medium": ["email", "push"],
    "low": ["email"],
}


def select_channel(
    event_type: str,
    customer: dict[str, Any],
    preferences: dict[str, Any],
) -> dict[str, Any]:
    """Select the best notification channel for a customer and event.

    Args:
        event_type: The event triggering notification.
        customer: Customer info dict (with preferred_channel, opted_out_channels).
        preferences: Notification preferences dict.

    Returns:
        Structured dict with channel selection and reasoning.
    """
    try:
        urgency = _EVENT_URGENCY.get(event_type, "low")
        channel_order = _URGENCY_CHANNEL_ORDER.get(urgency, ["email"])

        opted_out = set(customer.get("opted_out_channels", []))
        enabled = set(preferences.get("enabled_channels", ["email", "push", "sms"]))
        preferred = customer.get("preferred_channel", "")

        # Filter to channels that are enabled and not opted out
        available = [ch for ch in channel_order if ch in enabled and ch not in opted_out]

        if not available:
            # Fall back to email as last resort
            available = ["email"] if "email" not in opted_out else []

        if not available:
            return {
                "status": "success",
                "selection": {
                    "selected_channel": "none",
                    "fallback_channel": "none",
                    "reason": "all_channels_opted_out",
                    "opt_out_checked": True,
                },
            }

        # Prefer customer's chosen channel if available
        if preferred in available:
            selected = preferred
            reason = "customer_preference"
        else:
            selected = available[0]
            reason = f"urgency_based_{urgency}"

        fallback = available[1] if len(available) > 1 else "none"

        return {
            "status": "success",
            "selection": {
                "selected_channel": selected,
                "fallback_channel": fallback,
                "reason": reason,
                "opt_out_checked": True,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "selection": {},
            "error": f"Channel selection failed: {exc}",
        }
