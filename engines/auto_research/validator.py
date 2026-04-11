"""Validator — checks the output structure and quality before delivery.

Responsibility: ensure the final engine output conforms to the
``ResearchOutput`` schema and that quality minimums are met.

Model note: would use **Mistral** for semantic validation.
"""
from __future__ import annotations

import copy
from typing import Any

from .types import ValidationResult


# ---------------------------------------------------------------------------
# Required schema keys
# ---------------------------------------------------------------------------

_TOP_KEYS = {"status", "data", "meta", "error"}
_DATA_KEYS = {"insight", "key_findings", "recommended_action", "confidence"}
_META_KEYS = {"engine", "sources", "timestamp", "elapsed_seconds"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_output(output: dict[str, Any]) -> ValidationResult:
    """Validate the structure and quality of a research engine output.

    Never mutates *output* — works on a deep copy.
    Returns a ``ValidationResult`` indicating pass/fail with issue details.
    """
    safe_output: dict[str, Any] = copy.deepcopy(output)
    issues: list[str] = []

    # --- Structural checks ---

    # Top-level keys
    missing_top = _TOP_KEYS - set(safe_output.keys())
    if missing_top:
        issues.append(f"Missing top-level keys: {sorted(missing_top)}")

    # Data block
    data = safe_output.get("data")
    if safe_output.get("status") == "success":
        if data is None:
            issues.append("Status is 'success' but data is None.")
        elif isinstance(data, dict):
            missing_data = _DATA_KEYS - set(data.keys())
            if missing_data:
                issues.append(f"Missing data keys: {sorted(missing_data)}")
            else:
                # Content quality checks
                _check_data_quality(data, issues)
        else:
            issues.append(f"data should be a dict, got {type(data).__name__}.")

    # Meta block
    meta = safe_output.get("meta")
    if isinstance(meta, dict):
        missing_meta = _META_KEYS - set(meta.keys())
        if missing_meta:
            issues.append(f"Missing meta keys: {sorted(missing_meta)}")

        if meta.get("engine") != "auto_research":
            issues.append(
                f"Expected engine='auto_research', got '{meta.get('engine')}'."
            )

        elapsed = meta.get("elapsed_seconds")
        if isinstance(elapsed, (int, float)) and elapsed < 0:
            issues.append("elapsed_seconds cannot be negative.")
    else:
        issues.append("meta should be a dict.")

    # Error field
    if safe_output.get("status") == "success" and safe_output.get("error") is not None:
        issues.append("Status is 'success' but error is not None.")

    return ValidationResult(
        valid=len(issues) == 0,
        issues=issues,
    )


# ---------------------------------------------------------------------------
# Quality sub-checks
# ---------------------------------------------------------------------------

def _check_data_quality(data: dict[str, Any], issues: list[str]) -> None:
    """Validate data field content quality."""
    # Insight must be non-empty string
    insight = data.get("insight", "")
    if not isinstance(insight, str) or len(insight.strip()) < 10:
        issues.append("Insight is too short or not a string (min 10 chars).")

    # Key findings must be a non-empty list
    findings = data.get("key_findings", [])
    if not isinstance(findings, list):
        issues.append("key_findings must be a list.")
    elif len(findings) == 0:
        issues.append("key_findings is empty — at least one finding expected.")

    # Recommended action must be non-empty string
    action = data.get("recommended_action", "")
    if not isinstance(action, str) or len(action.strip()) < 10:
        issues.append("recommended_action is too short or not a string (min 10 chars).")

    # Confidence must be 0–1 float
    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)):
        issues.append("confidence must be a number.")
    elif not (0.0 <= confidence <= 1.0):
        issues.append(f"confidence must be 0.0–1.0, got {confidence}.")
