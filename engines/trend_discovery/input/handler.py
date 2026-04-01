"""Trend Discovery Engine — input validation and standardization."""
from __future__ import annotations
import copy, time
from typing import Any

REQUIRED_FIELDS = []  # Category or keywords recommended but not required
OPTIONAL_DEFAULTS = {"category": "", "keywords": [], "social_trends": [], "marketplace_products": [], "trend_name": ""}

def validate_and_standardize(input_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(input_payload, dict):
        return _fail("Input must be dict")
    if input_payload.get("status") == "fail":
        return _fail("Input already failed")
    raw = input_payload.get("data")
    if not isinstance(raw, dict):
        return _fail("Input.data must be dict")

    data = copy.deepcopy(raw)
    for field, default in OPTIONAL_DEFAULTS.items():
        if field not in data:
            data[field] = default

    if data.get("category"):
        data["category"] = str(data["category"]).strip().lower().replace(" ", "_")

    return {"status": "success", "data": data, "meta": {"engine": "trend_discovery", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": None}

def _fail(reason: str) -> dict[str, Any]:
    return {"status": "fail", "data": None, "meta": {"engine": "trend_discovery", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": {"reason": reason}}
