"""Aggregation constraint rules for score reliability.

These rules define the guardrails that ensure aggregated scores are
trustworthy. Violating critical rules means the unified score should
be treated with caution or rejected entirely.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Aggregation rule definitions
# ---------------------------------------------------------------------------
AGGREGATION_RULES: dict[str, dict[str, Any]] = {
    "minimum_engine_coverage": {
        "description": "At least 3 engine scores required for a reliable decision",
        "threshold": 3,
        "severity": "critical",
        "action": "Gather data from additional engines before making a selection decision",
    },
    "risk_score_required": {
        "description": "Risk score must be present — it acts as a multiplier on the overall score",
        "severity": "warning",
        "action": "Run risk assessment before finalizing; missing risk = conservative penalty applied",
    },
    "filter_fail_penalty": {
        "description": "Any engine returning fail status incurs a penalty on the unified score",
        "penalty_points": 20,
        "severity": "critical",
        "action": "Resolve filter failures — they indicate hard blockers like legal or shipping issues",
    },
    "profitability_required": {
        "description": "Profitability score must be present for any product considered for selection",
        "severity": "warning",
        "action": "Cannot select a product without knowing if it is profitable — run profitability engine",
    },
    "no_single_engine_dominance": {
        "description": "No single engine should contribute more than 35% of the unified score",
        "max_contribution_pct": 0.35,
        "severity": "info",
        "action": "Rebalance weights if one engine is dominating the decision",
    },
    "conflict_escalation": {
        "description": "Critical conflicts between engines require manual review",
        "severity": "critical",
        "action": "Do not auto-select when engines strongly disagree — escalate to human review",
    },
    "stale_data_penalty": {
        "description": "Engine data older than 30 days should be penalized or refreshed",
        "max_age_days": 30,
        "penalty_per_30_days": 5,
        "severity": "warning",
        "action": "Re-run stale engines to ensure data reflects current market conditions",
    },
    "minimum_confidence_for_auto_select": {
        "description": "Auto-selection requires moderate or high confidence level",
        "min_confidence": "moderate",
        "severity": "critical",
        "action": "Low-confidence scores should not drive automatic product selection",
    },
}


def validate_aggregation_inputs(
    raw_scores: dict[str, float | None],
    product: dict[str, Any],
) -> dict[str, Any]:
    """Validate engine scores against aggregation rules.

    Args:
        raw_scores: dict of engine_name -> raw score or None.
        product: full product dict with engine outputs.

    Returns:
        Dict with violations, warnings, penalties, and passed rules.
    """
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    penalties: list[dict[str, Any]] = []
    passed: list[str] = []

    available = [k for k, v in raw_scores.items() if v is not None]
    missing = [k for k, v in raw_scores.items() if v is None]

    # --- Minimum engine coverage ---
    rule = AGGREGATION_RULES["minimum_engine_coverage"]
    if len(available) < rule["threshold"]:
        violations.append({
            "rule": "minimum_engine_coverage",
            "severity": rule["severity"],
            "engines_available": len(available),
            "threshold": rule["threshold"],
            "missing": missing,
            "action": rule["action"],
        })
    else:
        passed.append("minimum_engine_coverage")

    # --- Risk score required ---
    rule = AGGREGATION_RULES["risk_score_required"]
    if raw_scores.get("risk") is None:
        warnings.append({
            "rule": "risk_score_required",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("risk_score_required")

    # --- Profitability required ---
    rule = AGGREGATION_RULES["profitability_required"]
    if raw_scores.get("profitability") is None:
        warnings.append({
            "rule": "profitability_required",
            "severity": rule["severity"],
            "action": rule["action"],
        })
    else:
        passed.append("profitability_required")

    # --- Filter fail penalty ---
    rule = AGGREGATION_RULES["filter_fail_penalty"]
    filt = product.get("filter")
    if filt is not None and filt.get("passed") is False:
        fail_reasons = filt.get("fail_reasons", [])
        penalty_amount = rule["penalty_points"]
        penalties.append({
            "rule": "filter_fail_penalty",
            "severity": rule["severity"],
            "amount": penalty_amount,
            "reasons": fail_reasons,
            "action": rule["action"],
        })
    elif filt is not None:
        passed.append("filter_fail_penalty")

    return {
        "valid": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "penalties": penalties,
        "passed_rules": passed,
        "engines_available": len(available),
        "engines_missing": len(missing),
    }


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
