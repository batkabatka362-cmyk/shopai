"""Alternative Presenter — constraint rules for alternative presentation.

Ensures at least one alternative is shown, explanations are clear about
why alternatives were not selected, and close seconds are flagged for
potential revisiting.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Alternative presentation rule definitions
# ---------------------------------------------------------------------------
ALTERNATIVE_RULES: dict[str, dict[str, Any]] = {
    "minimum_alternatives": {
        "description": "Must show at least 1 alternative product that was considered",
        "threshold": 1,
        "severity": "critical",
        "action": "Include the next-best candidate even if the gap is large",
    },
    "must_explain_rejection": {
        "description": "Each alternative must include why it was not chosen",
        "severity": "critical",
        "action": "Add rejection reason — 'it scored lower' is not enough",
    },
    "flag_close_seconds": {
        "description": "Alternatives within 5 points must be flagged as close seconds",
        "gap_threshold": 5.0,
        "severity": "warning",
        "action": "Mark close alternatives as backup options worth revisiting",
    },
    "max_alternatives": {
        "description": "Show no more than 3 alternatives to avoid information overload",
        "threshold": 3,
        "severity": "info",
        "action": "Limit to top 3 alternatives by score",
    },
    "must_include_scores": {
        "description": "Each alternative must show its unified score for comparison",
        "severity": "warning",
        "action": "Add the score so the reader can compare directly",
    },
    "show_alternative_strengths": {
        "description": "Note any dimensions where the alternative outperforms the selection",
        "severity": "info",
        "action": "Fair comparison builds trust — show where alternatives are stronger",
    },
}


def validate_alternatives(
    alternatives: list[dict[str, Any]],
    selected: dict[str, Any],
) -> dict[str, Any]:
    """Validate alternative presentation against all rules.

    Args:
        alternatives: List of alternative report dicts.
        selected: The selected product dict.

    Returns:
        Dict with valid flag, violations, warnings, and passed rules.
    """
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[str] = []

    # --- Minimum alternatives ---
    rule = ALTERNATIVE_RULES["minimum_alternatives"]
    if len(alternatives) < rule["threshold"]:
        violations.append({
            "rule": "minimum_alternatives",
            "severity": rule["severity"],
            "detail": f"Found {len(alternatives)} alternatives (min {rule['threshold']})",
            "action": rule["action"],
        })
    else:
        passed.append("minimum_alternatives")

    # --- Must explain rejection ---
    rule = ALTERNATIVE_RULES["must_explain_rejection"]
    missing_reason = [
        a for a in alternatives
        if not a.get("rejection_reason") or not a["rejection_reason"].get("primary_reason")
    ]
    if missing_reason:
        violations.append({
            "rule": "must_explain_rejection",
            "severity": rule["severity"],
            "detail": f"{len(missing_reason)} alternative(s) missing rejection reason",
            "action": rule["action"],
        })
    else:
        passed.append("must_explain_rejection")

    # --- Flag close seconds ---
    rule = ALTERNATIVE_RULES["flag_close_seconds"]
    close = [a for a in alternatives if a.get("score_gap", 999) <= rule["gap_threshold"]]
    unflagged = [a for a in close if not a.get("is_close_second")]
    if unflagged:
        warnings.append({
            "rule": "flag_close_seconds",
            "severity": rule["severity"],
            "detail": f"{len(unflagged)} close alternative(s) not flagged as close seconds",
            "action": rule["action"],
        })
    else:
        passed.append("flag_close_seconds")

    # --- Max alternatives ---
    rule = ALTERNATIVE_RULES["max_alternatives"]
    if len(alternatives) > rule["threshold"]:
        warnings.append({
            "rule": "max_alternatives",
            "severity": rule["severity"],
            "detail": f"Showing {len(alternatives)} alternatives (max {rule['threshold']})",
            "action": rule["action"],
        })
    else:
        passed.append("max_alternatives")

    # --- Must include scores ---
    rule = ALTERNATIVE_RULES["must_include_scores"]
    no_score = [a for a in alternatives if a.get("unified_score") is None]
    if no_score:
        warnings.append({
            "rule": "must_include_scores",
            "severity": rule["severity"],
            "detail": f"{len(no_score)} alternative(s) missing unified score",
            "action": rule["action"],
        })
    else:
        passed.append("must_include_scores")

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "passed_rules": passed,
        "total_alternatives": len(alternatives),
        "close_seconds": len(close),
    }
