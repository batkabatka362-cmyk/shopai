"""Trend Discovery Engine — output validation."""
from __future__ import annotations
from typing import Any

def validate_result(output: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {"valid": False, "reason": "Output must be dict"}
    for field in ("status", "data", "meta", "error"):
        if field not in output:
            return {"valid": False, "reason": f"Missing: {field}"}
    if output["status"] == "success" and not isinstance(output.get("data"), dict):
        return {"valid": False, "reason": "Success but data not dict"}
    meta = output.get("meta", {})
    for field in ("engine", "confidence", "timestamp"):
        if field not in meta:
            return {"valid": False, "reason": f"Missing meta.{field}"}
    if not (0 <= meta.get("confidence", 0) <= 1):
        return {"valid": False, "reason": "Confidence not 0-1"}
    return {"valid": True, "reason": "OK"}
