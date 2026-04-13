"""Supplier Discovery Engine — output validation."""
from __future__ import annotations
from typing import Any

OUTPUT_CONTRACT = {
    "top_level": ["status", "data", "meta", "error"],
    "meta_required": ["engine", "confidence", "timestamp"],
}

def validate_result(output: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {"valid": False, "reason": "Output must be dict"}
    for field in OUTPUT_CONTRACT["top_level"]:
        if field not in output:
            return {"valid": False, "reason": f"Missing: {field}"}
    if output["status"] not in ("success", "fail"):
        return {"valid": False, "reason": f"Invalid status: {output['status']}"}
    if output["status"] == "success" and not isinstance(output.get("data"), dict):
        return {"valid": False, "reason": "Success but data not dict"}
    meta = output.get("meta", {})
    for field in OUTPUT_CONTRACT["meta_required"]:
        if field not in meta:
            return {"valid": False, "reason": f"Missing meta: {field}"}
    conf = meta.get("confidence", 0)
    if not (0 <= conf <= 1):
        return {"valid": False, "reason": f"Confidence {conf} out of range"}
    return {"valid": True, "reason": "OK"}
