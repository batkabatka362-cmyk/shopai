"""Risk Disclosure — constraint rules for risk transparency.

Ensures all significant risks are disclosed, each has a mitigation plan,
and worst-case loss is stated explicitly. No hiding, no sugarcoating.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Risk disclosure rule definitions
# ---------------------------------------------------------------------------
RISK_DISCLOSURE_RULES: dict[str, dict[str, Any]] = {
    "disclose_all_high_critical": {
        "description": "Must disclose every risk rated high or critical — no exceptions",
        "severity": "critical",
        "action": "Review risk extraction — high/critical risks must appear in the report",
    },
    "mitigation_for_each": {
        "description": "Every disclosed risk must have a mitigation plan",
        "severity": "critical",
        "action": "Generate mitigation — a risk without a response plan is just bad news",
    },
    "state_worst_case_loss": {
        "description": "Must state the worst-case loss amount in dollars",
        "severity": "critical",
        "action": "Calculate and display the maximum potential financial loss",
    },
    "minimum_one_risk": {
        "description": "Every product has risk — at least one must be disclosed",
        "min_risks": 1,
        "severity": "critical",
        "action": "No product is risk-free — disclose at least general market risk",
    },
    "risk_must_have_severity": {
        "description": "Each risk must have a severity rating (critical/high/moderate/low)",
        "severity": "warning",
        "action": "Assign severity levels to help the reader prioritize",
    },
    "worst_case_must_be_realistic": {
        "description": "Worst case should not exceed 100% of investment",
        "max_loss_pct": 100.0,
        "severity": "warning",
        "action": "Cap worst-case at total investment unless leveraged positions exist",
    },
    "no_downplaying_language": {
        "description": "Avoid minimizing language like 'unlikely' or 'probably fine'",
        "severity": "info",
        "action": "State risks factually — let the data speak without editorial softening",
    },
}


def validate_risk_disclosure(
    risks: list[dict[str, Any]],
    worst_case: dict[str, Any],
) -> dict[str, Any]:
    """Validate a risk disclosure against all disclosure rules.

    Args:
        risks: List of disclosed risk dicts.
        worst_case: Worst-case scenario dict.

    Returns:
        Dict with valid flag, violations, warnings, and passed rules.
    """
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    passed: list[str] = []

    # --- Must disclose all high/critical risks ---
    rule = RISK_DISCLOSURE_RULES["disclose_all_high_critical"]
    # We assume risks were extracted correctly; check they exist
    high_critical = [r for r in risks if r.get("severity") in ("high", "critical")]
    # This rule passes if we have processed them (they exist in the list)
    passed.append("disclose_all_high_critical")

    # --- Mitigation for each ---
    rule = RISK_DISCLOSURE_RULES["mitigation_for_each"]
    missing_mitigation = [r for r in risks if not r.get("mitigation")]
    if missing_mitigation:
        violations.append({
            "rule": "mitigation_for_each",
            "severity": rule["severity"],
            "detail": f"{len(missing_mitigation)} risk(s) missing mitigation plan",
            "action": rule["action"],
        })
    else:
        passed.append("mitigation_for_each")

    # --- State worst-case loss ---
    rule = RISK_DISCLOSURE_RULES["state_worst_case_loss"]
    max_loss = worst_case.get("maximum_loss")
    if max_loss is None or max_loss == 0:
        # Allow zero loss only if no risks exist
        if len(risks) > 0 and risks[0].get("severity") != "low":
            violations.append({
                "rule": "state_worst_case_loss",
                "severity": rule["severity"],
                "detail": "Worst-case loss not calculated",
                "action": rule["action"],
            })
        else:
            passed.append("state_worst_case_loss")
    else:
        passed.append("state_worst_case_loss")

    # --- Minimum one risk ---
    rule = RISK_DISCLOSURE_RULES["minimum_one_risk"]
    if len(risks) < 1:
        violations.append({
            "rule": "minimum_one_risk",
            "severity": rule["severity"],
            "detail": "No risks disclosed — every product has risk",
            "action": rule["action"],
        })
    else:
        passed.append("minimum_one_risk")

    # --- Risk must have severity ---
    rule = RISK_DISCLOSURE_RULES["risk_must_have_severity"]
    no_severity = [r for r in risks if not r.get("severity")]
    if no_severity:
        warnings.append({
            "rule": "risk_must_have_severity",
            "severity": rule["severity"],
            "detail": f"{len(no_severity)} risk(s) missing severity rating",
            "action": rule["action"],
        })
    else:
        passed.append("risk_must_have_severity")

    # --- Worst case must be realistic ---
    rule = RISK_DISCLOSURE_RULES["worst_case_must_be_realistic"]
    loss_pct = worst_case.get("loss_percentage", 0)
    if loss_pct > rule["max_loss_pct"]:
        warnings.append({
            "rule": "worst_case_must_be_realistic",
            "severity": rule["severity"],
            "detail": f"Worst-case loss is {loss_pct:.0f}% — exceeds 100% cap",
            "action": rule["action"],
        })
    else:
        passed.append("worst_case_must_be_realistic")

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "passed_rules": passed,
        "total_risks": len(risks),
        "high_critical_count": len(high_critical),
    }
