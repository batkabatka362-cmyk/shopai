"""Demand Estimator — output validation."""
from __future__ import annotations
from typing import Any

def validate_result(output: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {"valid": False, "reason": "Not dict"}
    for f in ("status", "data", "meta", "error"):
        if f not in output:
            return {"valid": False, "reason": f"Missing {f}"}
    if output["status"] == "success" and not isinstance(output.get("data"), dict):
        return {"valid": False, "reason": "Data not dict"}
    return {"valid": True, "reason": "OK"}
