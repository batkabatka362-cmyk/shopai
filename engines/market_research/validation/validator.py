"""Market Research Engine — output validation (self-check).

Validates that engine output follows contract before returning.
Catches structural errors, missing fields, invalid values.
"""
from __future__ import annotations

from typing import Any


# Required output contract fields
OUTPUT_CONTRACT = {
    "top_level": ["status", "data", "meta", "error"],
    "meta_required": ["engine", "confidence", "timestamp"],
    "data_required": ["category", "verdict", "summary"],
}


def validate_result(output: dict[str, Any]) -> dict[str, Any]:
    """Validate engine output follows contract.

    Returns: {valid: bool, reason: str, checks: [...]}
    """
    checks = []

    # Check 1: Top-level structure
    for field in OUTPUT_CONTRACT["top_level"]:
        present = field in output
        checks.append({"field": field, "present": present})
        if not present:
            return {"valid": False, "reason": f"Missing top-level field: {field}", "checks": checks}

    # Check 2: Status is valid
    if output["status"] not in ("success", "fail"):
        return {"valid": False, "reason": f"Invalid status: {output['status']}", "checks": checks}

    # Check 3: If success, data must exist
    if output["status"] == "success":
        data = output.get("data")
        if not isinstance(data, dict):
            return {"valid": False, "reason": "Success status but data is not a dict", "checks": checks}

        for field in OUTPUT_CONTRACT["data_required"]:
            if field not in data:
                return {"valid": False, "reason": f"Missing data field: {field}", "checks": checks}

    # Check 4: Meta must have required fields
    meta = output.get("meta", {})
    if not isinstance(meta, dict):
        return {"valid": False, "reason": "Meta must be a dict", "checks": checks}

    for field in OUTPUT_CONTRACT["meta_required"]:
        if field not in meta:
            return {"valid": False, "reason": f"Missing meta field: {field}", "checks": checks}

    # Check 5: Confidence in valid range
    confidence = meta.get("confidence", 0)
    if not (0 <= confidence <= 1):
        return {"valid": False, "reason": f"Confidence {confidence} not in 0-1 range", "checks": checks}

    # Check 6: If fail, error must explain
    if output["status"] == "fail":
        error = output.get("error")
        if not isinstance(error, dict) or not error.get("reason"):
            return {"valid": False, "reason": "Fail status but no error.reason provided", "checks": checks}

    # Check 7: Verdict structure (if present)
    if output["status"] == "success":
        verdict = output["data"].get("verdict", {})
        if isinstance(verdict, dict):
            if "verdict" not in verdict or "score" not in verdict:
                return {"valid": False, "reason": "Verdict missing 'verdict' or 'score' field", "checks": checks}

    return {"valid": True, "reason": "OK", "checks": checks}
