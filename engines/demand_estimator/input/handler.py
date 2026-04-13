"""Demand Estimator — input validation."""
from __future__ import annotations
import copy, time
from typing import Any
from utils.helpers import safe_float, safe_int

def validate_and_standardize(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return _fail("Invalid input")
    data = copy.deepcopy(payload["data"])
    if not (data.get("category") or data.get("product_type") or data.get("keywords")):
        return _fail("Need category, product_type, or keywords")
    data.setdefault("category", data.get("product_type", "general"))
    data.setdefault("price", safe_float(data.get("target_price", 30)))
    data.setdefault("monthly_searches", safe_int(data.get("search_volume", 0)))
    return {"status": "success", "data": data, "meta": {"engine": "demand_estimator", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": None}

def _fail(r):
    return {"status": "fail", "data": None, "meta": {"engine": "demand_estimator", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": {"reason": r}}
