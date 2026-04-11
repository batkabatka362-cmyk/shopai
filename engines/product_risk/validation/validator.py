"""Product Risk Engine — output contract validation.

Ensures that the engine output conforms to the standard engine contract:
  {status, data, meta, error}

Also validates that product-risk-specific fields are present and well-formed
when the assessment succeeds.
"""
from __future__ import annotations

from typing import Any

REQUIRED_TOP_LEVEL = ("status", "data", "meta", "error")
REQUIRED_DATA_FIELDS = (
    "composite_risk_score",
    "risk_classification",
    "top_risks",
    "module_results",
)
REQUIRED_META_FIELDS = ("engine", "timestamp")
VALID_STATUSES = ("success", "fail", "error")
VALID_CLASSIFICATIONS = ("low", "moderate", "elevated", "high", "critical")


def validate_result(output: dict[str, Any]) -> dict[str, Any]:
    """Validate the engine output contract.

    Returns {valid: bool, reason: str, warnings: [...]}.
    """
    warnings: list[str] = []

    # Check type
    if not isinstance(output, dict):
        return _invalid("Output must be a dictionary")

    # Check top-level fields
    for field in REQUIRED_TOP_LEVEL:
        if field not in output:
            return _invalid(f"Missing required top-level field: '{field}'")

    # Check status value
    status = output["status"]
    if status not in VALID_STATUSES:
        return _invalid(
            f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}"
        )

    # For non-success, data can be None but error should be present
    if status in ("fail", "error"):
        if output.get("error") is None:
            warnings.append("Status is fail/error but error field is None")
        return _valid(warnings)

    # For success: validate data structure
    data = output.get("data")
    if not isinstance(data, dict):
        return _invalid("On success, 'data' must be a dictionary")

    for field in REQUIRED_DATA_FIELDS:
        if field not in data:
            return _invalid(f"Missing required data field: '{field}'")

    # Validate composite_risk_score range
    score = data.get("composite_risk_score")
    if not isinstance(score, (int, float)):
        return _invalid("composite_risk_score must be numeric")
    if not 0.0 <= score <= 1.0:
        warnings.append(
            f"composite_risk_score {score} is outside expected range [0, 1]"
        )

    # Validate risk_classification
    classification = data.get("risk_classification")
    if classification not in VALID_CLASSIFICATIONS:
        warnings.append(
            f"Unexpected risk_classification '{classification}'. "
            f"Expected one of: {VALID_CLASSIFICATIONS}"
        )

    # Validate top_risks is a list
    top_risks = data.get("top_risks")
    if not isinstance(top_risks, list):
        return _invalid("top_risks must be a list")

    # Validate module_results is a dict
    module_results = data.get("module_results")
    if not isinstance(module_results, dict):
        return _invalid("module_results must be a dictionary")

    # Validate meta
    meta = output.get("meta")
    if isinstance(meta, dict):
        for field in REQUIRED_META_FIELDS:
            if field not in meta:
                warnings.append(f"Missing recommended meta field: '{field}'")
    else:
        warnings.append("meta should be a dictionary")

    return _valid(warnings)


def _valid(warnings: list[str] | None = None) -> dict[str, Any]:
    """Return a valid result."""
    return {
        "valid": True,
        "reason": "OK",
        "warnings": warnings or [],
    }


def _invalid(reason: str) -> dict[str, Any]:
    """Return an invalid result."""
    return {
        "valid": False,
        "reason": reason,
        "warnings": [],
    }
