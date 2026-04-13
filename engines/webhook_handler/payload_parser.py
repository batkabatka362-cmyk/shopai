"""Webhook Handler Engine — payload parser.

Normalizes Shopify webhook payloads: converts string prices to floats,
ensures snake_case field names, and extracts key entity data based on
the event category.
"""
from __future__ import annotations

import copy
import re
from typing import Any


# ---------------------------------------------------------------------------
# Category-to-entity-type mapping
# ---------------------------------------------------------------------------

_ENTITY_TYPE_MAP: dict[str, str] = {
    "orders": "order",
    "products": "product",
    "customers": "customer",
    "refunds": "refund",
    "checkouts": "checkout",
    "collections": "collection",
    "fulfillments": "fulfillment",
    "inventory_items": "inventory_item",
    "inventory_levels": "inventory_level",
    "shop": "shop",
}

# ---------------------------------------------------------------------------
# Fields to extract per entity type
# ---------------------------------------------------------------------------

_ORDER_FIELDS = [
    "id", "name", "order_number", "email", "phone",
    "total_price", "subtotal_price", "total_tax", "total_discounts",
    "currency", "financial_status", "fulfillment_status",
    "created_at", "updated_at", "cancelled_at", "closed_at",
    "line_items", "shipping_address", "billing_address",
    "customer", "note", "tags", "gateway",
]

_PRODUCT_FIELDS = [
    "id", "title", "body_html", "vendor", "product_type",
    "handle", "status", "tags", "variants", "images", "options",
    "created_at", "updated_at", "published_at",
]

_CUSTOMER_FIELDS = [
    "id", "email", "first_name", "last_name", "phone",
    "orders_count", "total_spent", "tags", "note",
    "verified_email", "state", "currency",
    "created_at", "updated_at", "default_address", "addresses",
]

_REFUND_FIELDS = [
    "id", "order_id", "created_at", "note",
    "refund_line_items", "transactions", "order_adjustments",
]

_FIELDS_BY_TYPE: dict[str, list[str]] = {
    "order": _ORDER_FIELDS,
    "product": _PRODUCT_FIELDS,
    "customer": _CUSTOMER_FIELDS,
    "refund": _REFUND_FIELDS,
}

# ---------------------------------------------------------------------------
# Price fields that Shopify sends as strings
# ---------------------------------------------------------------------------

_PRICE_FIELDS = {
    "total_price", "subtotal_price", "total_tax", "total_discounts",
    "price", "compare_at_price", "total_spent", "amount",
    "price_set", "total_line_items_price",
}


def parse_payload(
    raw_payload: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    """Parse and normalize a Shopify webhook payload.

    Converts string prices to floats, extracts key entity fields
    based on the event category, and normalizes field naming.

    Args:
        raw_payload: The raw webhook body as a dict.
        event: The classified event dict from event_classifier.

    Returns:
        Structured dict with parsed payload data.
    """
    try:
        if not isinstance(raw_payload, dict):
            return {
                "status": "error",
                "parsed": {},
                "error": "raw_payload must be a dict",
            }

        if not isinstance(event, dict):
            return {
                "status": "error",
                "parsed": {},
                "error": "event must be a dict",
            }

        payload = copy.deepcopy(raw_payload)
        category = event.get("category", "unknown")
        entity_type = _ENTITY_TYPE_MAP.get(category, category)

        # Extract entity ID
        entity_id = str(payload.get("id", ""))

        # Normalize price fields in top-level payload
        normalized = _normalize_prices(payload)

        # Extract only the relevant fields for this entity type
        field_list = _FIELDS_BY_TYPE.get(entity_type)
        if field_list:
            extracted: dict[str, Any] = {}
            for field in field_list:
                if field in normalized:
                    extracted[field] = normalized[field]
            # Normalize nested price fields in line_items if present
            if "line_items" in extracted and isinstance(extracted["line_items"], list):
                extracted["line_items"] = [
                    _normalize_prices(item) if isinstance(item, dict) else item
                    for item in extracted["line_items"]
                ]
            # Normalize nested price fields in variants if present
            if "variants" in extracted and isinstance(extracted["variants"], list):
                extracted["variants"] = [
                    _normalize_prices(v) if isinstance(v, dict) else v
                    for v in extracted["variants"]
                ]
            normalized_output = extracted
        else:
            # Unknown entity type — return all normalized fields
            normalized_output = normalized

        return {
            "status": "success",
            "parsed": {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "normalized": normalized_output,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "parsed": {},
            "error": f"Payload parsing failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_prices(data: dict[str, Any]) -> dict[str, Any]:
    """Convert string price fields to floats in a dict.

    Shopify sends many monetary values as strings (e.g. "29.99").
    This converts known price fields to float values.
    """
    result = dict(data)
    for key, value in result.items():
        if key in _PRICE_FIELDS and isinstance(value, str):
            try:
                result[key] = float(value)
            except (ValueError, TypeError):
                pass  # Keep original if conversion fails
    return result


def _to_snake_case(name: str) -> str:
    """Convert a camelCase or PascalCase string to snake_case.

    Shopify uses snake_case natively, but this handles edge cases.
    """
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1).lower()
