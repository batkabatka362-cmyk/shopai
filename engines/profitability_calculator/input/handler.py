"""Profitability Calculator — input validation."""
from __future__ import annotations
import copy, time
from typing import Any
from utils.helpers import safe_float, safe_int

def validate_and_standardize(input_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(input_payload, dict) or not isinstance(input_payload.get("data"), dict):
        return _fail("Invalid input")
    data = copy.deepcopy(input_payload["data"])
    if not data.get("price") and not data.get("retail_price"):
        return _fail("Need price or retail_price")
    data.setdefault("price", safe_float(data.get("retail_price", 0)))
    data.setdefault("cost", safe_float(data.get("cogs", data.get("unit_cost", 0))))
    data.setdefault("monthly_volume", safe_int(data.get("estimated_monthly_demand", 50)))
    data.setdefault("weight_kg", safe_float(data.get("product_weight_kg", 1.0)))
    data.setdefault("ad_spend_monthly", safe_float(data.get("marketing_budget", 500)))
    data.setdefault("budget", safe_float(data.get("initial_investment", 3000)))
    return {"status": "success", "data": data, "meta": {"engine": "profitability_calculator", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": None}

def _fail(reason: str) -> dict[str, Any]:
    return {"status": "fail", "data": None, "meta": {"engine": "profitability_calculator", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": {"reason": reason}}
