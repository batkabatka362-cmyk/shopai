"""Product Risk Engine — input validation and standardization.

Validates that the incoming payload contains sufficient information to
run a product risk assessment. Requires at minimum a product_type or category.
"""
from __future__ import annotations

import copy
import time
from typing import Any

ENGINE_NAME = "product_risk"

REQUIRED_FIELDS = ("category", "product_type")

DEFAULTS: dict[str, Any] = {
    "category": "general",
    "price": 30.0,
    "monthly_fixed_costs": 5000.0,
    "monthly_variable_costs": 3000.0,
    "cash_reserve_months": 0,
    "inventory_months_on_hand": 0,
    "expected_monthly_revenue": 10000.0,
    "weather_dependent": False,
    "has_weather_contingency": False,
    "supplier_count": 1,
    "lead_time_days": 30,
}


def validate_and_standardize(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate input payload and fill defaults.

    Requires at least one of: category, product_type.
    Returns engine contract: {status, data, meta, error}.
    """
    if not isinstance(payload, dict):
        return _fail("Payload must be a dictionary")

    raw_data = payload.get("data", payload)
    if not isinstance(raw_data, dict):
        return _fail("Payload 'data' field must be a dictionary")

    # Check for required identifiers
    has_identifier = any(raw_data.get(f) for f in REQUIRED_FIELDS)
    if not has_identifier:
        return _fail(
            "Need at least one of: product_type, category. "
            "Cannot assess risk without knowing what the product is."
        )

    data = copy.deepcopy(raw_data)

    # Normalize: ensure category is always set
    if not data.get("category"):
        data["category"] = data.get("product_type", "general")

    # Apply defaults for optional fields
    for field, default in DEFAULTS.items():
        data.setdefault(field, default)

    # Coerce numeric fields
    for numeric_field in (
        "price", "monthly_fixed_costs", "monthly_variable_costs",
        "cash_reserve_months", "inventory_months_on_hand",
        "expected_monthly_revenue", "supplier_count", "lead_time_days",
    ):
        val = data.get(numeric_field)
        if val is not None:
            try:
                data[numeric_field] = float(val)
            except (ValueError, TypeError):
                data[numeric_field] = DEFAULTS.get(numeric_field, 0)

    # Validate launch_month if present
    launch = data.get("launch_month")
    if launch is not None:
        try:
            launch = int(launch)
            if not 1 <= launch <= 12:
                return _fail(f"launch_month must be 1-12, got {launch}")
            data["launch_month"] = launch
        except (ValueError, TypeError):
            return _fail(f"launch_month must be an integer 1-12, got {launch!r}")

    # Ensure trend_data is a dict if present
    if "trend_data" in data and not isinstance(data["trend_data"], dict):
        data["trend_data"] = {}

    return {
        "status": "success",
        "data": data,
        "meta": {
            "engine": ENGINE_NAME,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": None,
    }


def _fail(reason: str) -> dict[str, Any]:
    """Build a standard failure response."""
    return {
        "status": "fail",
        "data": None,
        "meta": {
            "engine": ENGINE_NAME,
            "confidence": 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "error": {"reason": reason},
    }
