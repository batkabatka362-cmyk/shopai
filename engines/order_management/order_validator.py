"""Order Management Engine — order validator.

Validates order structure, required fields, line items, email format,
and shipping address completeness.

All validation is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import re
from typing import Any

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

_REQUIRED_ORDER_FIELDS = ("id", "email", "line_items", "shipping_address", "total_price")
_REQUIRED_ADDRESS_FIELDS = ("address1", "city", "country_code")


def validate_order(order: dict[str, Any]) -> dict[str, Any]:
    """Validate an order for required fields and data integrity.

    Args:
        order: Order dict to validate.

    Returns:
        Structured dict with validation status, validity flag, and errors.
    """
    try:
        order = copy.deepcopy(order)
        errors: list[str] = []

        # --- Required top-level fields ---
        for field in _REQUIRED_ORDER_FIELDS:
            if field not in order or order[field] is None:
                errors.append(f"Missing required field: {field}")

        # --- Email format ---
        email = order.get("email", "")
        if email and not _EMAIL_RE.match(str(email)):
            errors.append(f"Invalid email format: {email}")

        # --- Line items validation ---
        line_items = order.get("line_items")
        if isinstance(line_items, list):
            if len(line_items) == 0:
                errors.append("Order must have at least one line item")
            for idx, item in enumerate(line_items):
                if not isinstance(item, dict):
                    errors.append(f"Line item {idx} is not a dict")
                    continue
                if not item.get("product_id"):
                    errors.append(f"Line item {idx} missing product_id")
                qty = item.get("quantity", 0)
                if not isinstance(qty, (int, float)) or qty <= 0:
                    errors.append(f"Line item {idx} quantity must be > 0")
                price = item.get("price")
                if price is not None and (not isinstance(price, (int, float)) or price < 0):
                    errors.append(f"Line item {idx} price must be >= 0")
        elif "line_items" in order:
            errors.append("line_items must be a list")

        # --- Shipping address validation ---
        address = order.get("shipping_address")
        if isinstance(address, dict):
            for field in _REQUIRED_ADDRESS_FIELDS:
                if not address.get(field):
                    errors.append(f"Shipping address missing: {field}")
        elif "shipping_address" in order and address is not None:
            errors.append("shipping_address must be a dict")

        # --- Total price ---
        total_price = order.get("total_price")
        if total_price is not None:
            if not isinstance(total_price, (int, float)) or total_price < 0:
                errors.append("total_price must be a non-negative number")

        is_valid = len(errors) == 0

        return {
            "status": "success",
            "is_valid": is_valid,
            "errors": errors,
        }
    except Exception as exc:
        return {
            "status": "error",
            "is_valid": False,
            "errors": [f"Validation failed: {exc}"],
        }
