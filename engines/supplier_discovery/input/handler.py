"""Supplier Discovery Engine — input validation and standardization."""
from __future__ import annotations

import copy
import time
from typing import Any

from utils.helpers import safe_float, safe_int

SCHEMA = {
    "required": ["product_type"],
    "optional": {
        "target_price": 30,
        "target_quantity": 100,
        "budget": 5000,
        "target_margin": 0.50,
        "time_constraint_days": 60,
        "quality_priority": "medium",
        "customization_needed": False,
        "brand_own": False,
        "zero_inventory_preferred": False,
        "origin_country": "china",
        "destination_country": "us",
        "shipping_method": "sea_freight",
        "product_weight_kg": 1.0,
        "estimated_monthly_demand": 50,
        "storage_cost": 0.50,
        "suppliers": [],
    },
}


def validate_and_standardize(input_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(input_payload, dict) or not isinstance(input_payload.get("data"), dict):
        return _fail("Invalid input structure")

    if input_payload.get("status") == "fail":
        return _fail("Input already failed")

    data = copy.deepcopy(input_payload["data"])

    # Required
    if not data.get("product_type") and not data.get("category"):
        return _fail("Missing product_type or category")
    if not data.get("product_type"):
        data["product_type"] = data["category"]

    # Defaults
    for field, default in SCHEMA["optional"].items():
        if field not in data:
            data[field] = default

    # Type coercion
    data["target_price"] = safe_float(data["target_price"])
    data["target_quantity"] = safe_int(data["target_quantity"])
    data["budget"] = safe_float(data["budget"])
    data["target_margin"] = safe_float(data["target_margin"])
    data["product_weight_kg"] = safe_float(data["product_weight_kg"])

    return {"status": "success", "data": data, "meta": {"engine": "supplier_discovery", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": None}


def _fail(reason: str) -> dict[str, Any]:
    return {"status": "fail", "data": None, "meta": {"engine": "supplier_discovery", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": {"reason": reason}}
