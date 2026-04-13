"""Selection Reasoning Engine — output validation.

Validates the final engine output contract for structural completeness,
data integrity, and logical consistency. Ensures the reasoning report
has all required sections before returning to the caller.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Required top-level contract fields
# --------------------------------------------------------------------------- #
REQUIRED_CONTRACT_FIELDS = ("status", "data", "meta", "error")

# Required fields within data when status is success
REQUIRED_DATA_FIELDS = (
    "narrative",
    "citations",
    "risk_disclosure",
    "alternatives",
    "action_plan",
    "selected_product",
    "executive_summary",
)

# Required meta fields
REQUIRED_META_FIELDS = ("engine", "confidence", "timestamp")


def validate_result(output: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete engine output contract.

    Args:
        output: The formatted engine output dict.

    Returns:
        {valid: bool, reason: str, checks: list[dict]}
    """
    checks: list[dict[str, Any]] = []

    # --- Check 1: Output is a dict ---
    if not isinstance(output, dict):
        return _result(False, "Output is not a dictionary", checks)
    checks.append({"check": "is_dict", "passed": True})

    # --- Check 2: Required contract fields ---
    for field in REQUIRED_CONTRACT_FIELDS:
        present = field in output
        checks.append({"check": f"has_{field}", "passed": present})
        if not present:
            return _result(False, f"Missing required field: {field}", checks)

    # --- Check 3: Status is valid ---
    valid_statuses = ("success", "partial", "fail", "error")
    status = output.get("status")
    status_ok = status in valid_statuses
    checks.append({"check": "valid_status", "passed": status_ok})
    if not status_ok:
        return _result(False, f"Invalid status: {status}", checks)

    # --- Check 4: Data structure when success ---
    if status == "success":
        data = output.get("data")
        if not isinstance(data, dict):
            checks.append({"check": "data_is_dict", "passed": False})
            return _result(False, "Data must be a dictionary on success", checks)
        checks.append({"check": "data_is_dict", "passed": True})

        for field in REQUIRED_DATA_FIELDS:
            present = field in data
            checks.append({"check": f"data_has_{field}", "passed": present})
            if not present:
                return _result(False, f"Missing data field: {field}", checks)

        # --- Check 5: Narrative has content ---
        narrative = data.get("narrative", {})
        if isinstance(narrative, dict):
            has_summary = bool(narrative.get("summary"))
            checks.append({"check": "narrative_has_summary", "passed": has_summary})
            if not has_summary:
                return _result(False, "Narrative is missing summary", checks)

        # --- Check 6: Risk disclosure present ---
        risk = data.get("risk_disclosure", {})
        if isinstance(risk, dict):
            has_risks = isinstance(risk.get("risks"), list)
            checks.append({"check": "has_risk_list", "passed": has_risks})

        # --- Check 7: Action plan has steps ---
        plan = data.get("action_plan", {})
        if isinstance(plan, dict):
            has_steps = isinstance(plan.get("steps"), list) and len(plan.get("steps", [])) > 0
            checks.append({"check": "plan_has_steps", "passed": has_steps})

    # --- Check 8: Meta structure ---
    meta = output.get("meta")
    if isinstance(meta, dict):
        for field in REQUIRED_META_FIELDS:
            present = field in meta
            checks.append({"check": f"meta_has_{field}", "passed": present})
    else:
        checks.append({"check": "meta_is_dict", "passed": False})

    # --- Check 9: Confidence is within bounds ---
    if isinstance(meta, dict):
        conf = meta.get("confidence", 0)
        conf_ok = isinstance(conf, (int, float)) and 0 <= conf <= 1.0
        checks.append({"check": "confidence_in_range", "passed": conf_ok})

    # --- Check 10: Error field consistency ---
    if status == "success" and output.get("error") is not None:
        checks.append({"check": "no_error_on_success", "passed": False})

    return _result(True, "OK", checks)


def _result(valid: bool, reason: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a validation result dict."""
    return {
        "valid": valid,
        "reason": reason,
        "checks_run": len(checks),
        "checks_passed": sum(1 for c in checks if c.get("passed")),
        "checks": checks,
    }
