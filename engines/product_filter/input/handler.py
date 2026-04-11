"""Product Filter Engine — input validation."""
from __future__ import annotations
import copy, time
from typing import Any

def validate_and_standardize(input_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(input_payload, dict) or not isinstance(input_payload.get("data"), dict):
        return _fail("Invalid input structure")
    data = copy.deepcopy(input_payload["data"])
    if not data.get("products"):
        return _fail("No products to filter")
    if not isinstance(data["products"], list):
        return _fail("Products must be a list")
    data.setdefault("criteria", {})
    data.setdefault("brand_profile", {})
    return {"status": "success", "data": data, "meta": {"engine": "product_filter", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": None}

def _fail(reason: str) -> dict[str, Any]:
    return {"status": "fail", "data": None, "meta": {"engine": "product_filter", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": {"reason": reason}}
