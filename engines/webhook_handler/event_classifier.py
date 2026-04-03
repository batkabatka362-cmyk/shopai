"""Webhook Handler Engine — event classifier.

Parses Shopify webhook topic strings into structured event information
and assigns priority levels based on event category.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Priority mapping by category
# ---------------------------------------------------------------------------

_PRIORITY_MAP: dict[str, str] = {
    "orders": "high",
    "refunds": "high",
    "checkouts": "high",
    "products": "medium",
    "customers": "medium",
    "collections": "medium",
    "inventory_items": "medium",
    "inventory_levels": "medium",
    "fulfillments": "high",
    "shop": "low",
    "themes": "low",
    "app": "low",
}

_DEFAULT_PRIORITY = "medium"


def classify_event(
    topic: str,
    raw_payload: dict[str, Any],
) -> dict[str, Any]:
    """Classify a Shopify webhook event by topic.

    Parses the topic string (e.g. "orders/create") into category
    and action components, then assigns a priority level.

    Args:
        topic: The Shopify webhook topic (e.g. "orders/create").
        raw_payload: The raw webhook payload dict (used for additional
            context if the topic alone is ambiguous).

    Returns:
        Structured dict with event classification.
    """
    try:
        if not topic or not isinstance(topic, str):
            return {
                "status": "error",
                "event": {},
                "error": "Webhook topic is required and must be a non-empty string",
            }

        # Parse topic: "category/action" format
        parts = topic.strip().lower().split("/", 1)
        category = parts[0] if len(parts) > 0 else "unknown"
        action = parts[1] if len(parts) > 1 else "unknown"

        # Clean up category and action
        category = category.strip()
        action = action.strip()

        if not category:
            return {
                "status": "error",
                "event": {},
                "error": f"Could not parse category from topic: {topic}",
            }

        # Assign priority
        priority = _PRIORITY_MAP.get(category, _DEFAULT_PRIORITY)

        # Elevate priority for certain high-impact actions regardless of category
        if action in ("delete", "cancelled") and priority == "medium":
            priority = "high"

        event_info: dict[str, Any] = {
            "category": category,
            "action": action,
            "priority": priority,
            "topic": topic.strip().lower(),
        }

        return {
            "status": "success",
            "event": event_info,
        }
    except Exception as exc:
        return {
            "status": "error",
            "event": {},
            "error": f"Event classification failed: {exc}",
        }
