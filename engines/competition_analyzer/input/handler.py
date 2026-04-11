"""Competition Analyzer — input validation."""
from __future__ import annotations
import copy, time
from typing import Any

def validate_and_standardize(input_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(input_payload, dict) or not isinstance(input_payload.get("data"), dict):
        return _fail("Invalid input")
    data = copy.deepcopy(input_payload["data"])
    if not (data.get("product") or data.get("category") or data.get("competitors")):
        return _fail("Need product, category, or competitors data")
    data.setdefault("competitors", [])
    data.setdefault("category", "")
    data.setdefault("our_price", 0)
    data.setdefault("our_rating", 0)
    return {"status": "success", "data": data, "meta": {"engine": "competition_analyzer", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": None}

def _fail(reason: str) -> dict[str, Any]:
    return {"status": "fail", "data": None, "meta": {"engine": "competition_analyzer", "confidence": 0, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "error": {"reason": reason}}
