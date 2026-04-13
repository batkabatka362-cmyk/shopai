"""Webhook Handler Engine — engine router.

Maps webhook event category+action to target engine names.
Each route includes the target engine, action, priority, and payload key.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Routing table: (category, action) -> list of target engines
# ---------------------------------------------------------------------------

_ROUTING_TABLE: dict[tuple[str, str], list[dict[str, str]]] = {
    ("orders", "create"): [
        {"engine": "order_management", "payload_key": "order"},
        {"engine": "fraud_detection", "payload_key": "order"},
        {"engine": "inventory", "payload_key": "order"},
        {"engine": "tax_engine", "payload_key": "order"},
    ],
    ("orders", "updated"): [
        {"engine": "order_management", "payload_key": "order"},
    ],
    ("orders", "cancelled"): [
        {"engine": "order_management", "payload_key": "order"},
        {"engine": "inventory", "payload_key": "order"},
    ],
    ("orders", "fulfilled"): [
        {"engine": "order_management", "payload_key": "order"},
        {"engine": "shipping_optimization", "payload_key": "order"},
    ],
    ("products", "create"): [
        {"engine": "product_variant", "payload_key": "product"},
        {"engine": "catalog", "payload_key": "product"},
    ],
    ("products", "update"): [
        {"engine": "product_variant", "payload_key": "product"},
        {"engine": "dynamic_pricing", "payload_key": "product"},
    ],
    ("products", "delete"): [
        {"engine": "catalog", "payload_key": "product"},
        {"engine": "inventory", "payload_key": "product"},
    ],
    ("customers", "create"): [
        {"engine": "customer_segmentation", "payload_key": "customer"},
    ],
    ("customers", "update"): [
        {"engine": "customer_segmentation", "payload_key": "customer"},
    ],
    ("refunds", "create"): [
        {"engine": "order_management", "payload_key": "refund"},
        {"engine": "accounting", "payload_key": "refund"},
        {"engine": "cash_flow", "payload_key": "refund"},
    ],
}


def route_to_engines(
    event: dict[str, Any],
    parsed: dict[str, Any],
) -> dict[str, Any]:
    """Determine which engines should receive this webhook event.

    Looks up the event category+action in the routing table and returns
    the list of target engines with their dispatch metadata.

    Args:
        event: The classified event dict from event_classifier.
        parsed: The parsed payload dict from payload_parser.

    Returns:
        Structured dict with routing decisions.
    """
    try:
        if not isinstance(event, dict):
            return {
                "status": "error",
                "routes": [],
                "error": "event must be a dict",
            }

        category = event.get("category", "")
        action = event.get("action", "")
        priority = event.get("priority", "medium")

        if not category or not action:
            return {
                "status": "error",
                "routes": [],
                "error": f"Invalid event: category={category!r}, action={action!r}",
            }

        # Look up in routing table
        key = (category, action)
        target_entries = _ROUTING_TABLE.get(key, [])

        if not target_entries:
            # No explicit route — return empty with a note
            return {
                "status": "success",
                "routes": [],
                "note": f"No routes configured for {category}/{action}",
            }

        routes: list[dict[str, Any]] = []
        for entry in target_entries:
            routes.append({
                "engine": entry["engine"],
                "action": action,
                "priority": priority,
                "payload_key": entry.get("payload_key", category),
            })

        return {
            "status": "success",
            "routes": routes,
        }
    except Exception as exc:
        return {
            "status": "error",
            "routes": [],
            "error": f"Engine routing failed: {exc}",
        }
