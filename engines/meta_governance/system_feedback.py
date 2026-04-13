"""Meta-Intelligence Governance -- system feedback generator.

Generates feedback for the system about governance decisions,
providing actionable information for other engines to act on.

Model note: Would use Qwen for structured report formatting.
"""
from __future__ import annotations

import copy
from typing import Any


def generate_feedback(
    activity: dict[str, Any],
    decision: str,
    violations: list[dict[str, Any]],
    policy_checks: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    risk_score: float,
    risk_level: str,
    constraint_results: list[dict[str, Any]],
    validation_results: list[dict[str, Any]],
    validation_score: float,
    override_decision: dict[str, Any],
) -> dict[str, Any]:
    """Generate structured feedback about the governance decision.

    Args:
        activity: SystemActivity dict.
        decision: Final decision string.
        violations: Rule violations found.
        policy_checks: All policy check results.
        risks: All risk assessments.
        risk_score: Overall risk score.
        risk_level: Overall risk level string.
        constraint_results: All constraint check results.
        validation_results: All validation check results.
        validation_score: Average validation score.
        override_decision: Override handler result.

    Returns:
        Structured dict with feedback for the system.
    """
    try:
        action_type = activity.get("action_type", "unknown")
        source_engine = activity.get("source_engine", "unknown")

        # Collect all issues
        issues = _collect_issues(
            violations, policy_checks, constraint_results,
            validation_results, risk_level,
        )

        # Build risk summary
        risk_summary = _build_risk_summary(risks, risk_score, risk_level)

        # Build recommendations
        recommendations = _build_recommendations(
            decision, violations, policy_checks, risks,
            constraint_results, override_decision,
        )

        # Determine if any modifications were applied
        modifications = override_decision.get("modifications", {})
        suggested_fix = override_decision.get("suggested_fix")

        return {
            "status": "success",
            "feedback": {
                "source_engine": source_engine,
                "action_type": action_type,
                "decision": decision,
                "issues": issues,
                "risk_summary": risk_summary,
                "recommendations": recommendations,
                "modifications_applied": modifications,
                "suggested_fix": suggested_fix,
                "validation_score": round(validation_score, 4),
                "governance_confidence": _compute_governance_confidence(
                    risk_score, validation_score, len(violations), len(issues),
                ),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "feedback": {
                "source_engine": "unknown",
                "action_type": "unknown",
                "decision": "error",
                "issues": [f"Feedback generation failed: {exc}"],
                "risk_summary": {},
                "recommendations": [],
                "modifications_applied": {},
                "suggested_fix": None,
                "validation_score": 0.0,
                "governance_confidence": 0.0,
            },
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collect_issues(
    violations: list[dict[str, Any]],
    policy_checks: list[dict[str, Any]],
    constraint_results: list[dict[str, Any]],
    validation_results: list[dict[str, Any]],
    risk_level: str,
) -> list[str]:
    """Collect all issues into a flat list of human-readable strings."""
    issues: list[str] = []

    for v in violations:
        severity = v.get("severity", "warning")
        issues.append(f"[{severity}] {v.get('rule_name', 'unknown')}: {v.get('detail', '')}")

    for p in policy_checks:
        if not p.get("passed", True):
            issues.append(f"[policy] {p.get('policy_name', 'unknown')}: {p.get('detail', '')}")

    for c in constraint_results:
        if c.get("enforced", False):
            issues.append(f"[constraint] {c.get('constraint_name', 'unknown')}: {c.get('detail', '')}")

    for v in validation_results:
        if not v.get("passed", True):
            issues.append(f"[validation] {v.get('check_name', 'unknown')}: {v.get('detail', '')}")

    if risk_level in ("high", "critical"):
        issues.append(f"[risk] Overall risk level is {risk_level}")

    return issues


def _build_risk_summary(
    risks: list[dict[str, Any]],
    risk_score: float,
    risk_level: str,
) -> dict[str, Any]:
    """Build a compact risk summary."""
    return {
        "overall_score": round(risk_score, 4),
        "overall_level": risk_level,
        "dimensions": {
            r["risk_type"]: {
                "score": r["score"],
                "level": r["level"],
            }
            for r in risks
        },
    }


def _build_recommendations(
    decision: str,
    violations: list[dict[str, Any]],
    policy_checks: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    constraint_results: list[dict[str, Any]],
    override_decision: dict[str, Any],
) -> list[str]:
    """Build actionable recommendations."""
    recs: list[str] = []

    if decision == "rejected":
        recs.append("Action was rejected — address violations before retrying")
        fix = override_decision.get("suggested_fix")
        if fix:
            recs.append(f"Suggested fix: {fix}")
    elif decision == "modified":
        mods = override_decision.get("modifications", {})
        for key, val in mods.items():
            if key == "governance_warning":
                recs.append("Governance warning attached — monitor closely")
            else:
                recs.append(f"'{key}' was adjusted to {val}")
    elif decision == "approved_with_warning":
        recs.append("Action approved but monitor closely for issues")

    # Risk-specific recommendations
    high_risks = [r for r in risks if r.get("level") in ("high", "critical")]
    for r in high_risks:
        recs.append(f"Address {r['risk_type']} risk ({r['level']}): {r.get('detail', '')}")

    # Constraint near-misses
    near_misses = [
        c for c in constraint_results
        if not c.get("enforced") and c.get("actual_value") is not None
    ]
    for c in near_misses:
        limit = c.get("limit_value")
        actual = c.get("actual_value")
        if isinstance(limit, (int, float)) and isinstance(actual, (int, float)):
            if limit > 0 and actual / limit > 0.80:
                recs.append(
                    f"Near constraint limit: {c.get('constraint_name', '')} "
                    f"at {actual}/{limit}"
                )

    return recs


def _compute_governance_confidence(
    risk_score: float,
    validation_score: float,
    violation_count: int,
    issue_count: int,
) -> float:
    """Compute governance confidence in the decision."""
    confidence = 0.90  # start high

    # Risk lowers confidence
    confidence -= risk_score * 0.30

    # Low validation lowers confidence
    confidence -= max(0.60 - validation_score, 0) * 0.20

    # Violations lower confidence
    confidence -= min(violation_count * 0.05, 0.20)

    # Many issues lower confidence
    confidence -= min(issue_count * 0.02, 0.10)

    return round(max(confidence, 0.10), 4)
