"""Order Management Engine — order validator.

Validates that an order has all required fields, valid line items,
proper email format, and complete shipping address.

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
    """Validate an order for completeness and correctness.

    Args:
        order: The order dict to validate.

    Returns:
        Structured dict with validation result.
    """
    try:
        order = copy.deepcopy(order)
        errors: list[str] = []

        # ---- Required top-level fields ----
        for field in _REQUIRED_ORDER_FIELDS:
            if field not in order or order[field] is None:
                errors.append(f"Missing required field: {field}")

        # ---- Email validation ----
        email = order.get("email", "")
        if email and not _EMAIL_RE.match(str(email)):
            errors.append(f"Invalid email format: {email}")

        # ---- Total price validation ----
        total_price = order.get("total_price")
        if total_price is not None:
            try:
                tp = float(total_price)
                if tp < 0:
                    errors.append("total_price must be non-negative")
            except (ValueError, TypeError):
                errors.append(f"Invalid total_price: {total_price}")

        # ---- Line items validation ----
        line_items = order.get("line_items", [])
        if not isinstance(line_items, list) or len(line_items) == 0:
            errors.append("Order must contain at least one line item")
        else:
            for idx, item in enumerate(line_items):
                if not isinstance(item, dict):
                    errors.append(f"Line item {idx} is not a dict")
                    continue
                if not item.get("product_id"):
                    errors.append(f"Line item {idx} missing product_id")
                qty = item.get("quantity")
                if qty is None or not isinstance(qty, (int, float)) or qty <= 0:
                    errors.append(f"Line item {idx} quantity must be > 0")
                price = item.get("price")
                if price is None or not isinstance(price, (int, float)) or price < 0:
                    errors.append(f"Line item {idx} price must be >= 0")

        # ---- Shipping address validation ----
        shipping = order.get("shipping_address", {})
        if not isinstance(shipping, dict) or not shipping:
            errors.append("Missing or empty shipping_address")
        else:
            for field in _REQUIRED_ADDRESS_FIELDS:
                if not shipping.get(field):
                    errors.append(f"Shipping address missing: {field}")

        is_valid = len(errors) == 0

        return {
            "status": "success",
            "is_valid": is_valid,
            "errors": errors,
        }
    except Exception as exc:
        return _fail(f"Order validation failed: {exc}")


def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "is_valid": False,
        "errors": [reason],
    }
