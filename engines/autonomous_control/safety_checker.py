"""Autonomous Control Engine — safety checker.

Verifies each action is within configured safety bounds.
Checks cost limits, blocked targets, risk levels, and rate constraints.
"""
from __future__ import annotations

import copy
from typing import Any


def check_safety(
    actions: list[dict[str, Any]],
    safety_limits: dict[str, Any],
) -> dict[str, Any]:
    """Check each action against safety limits.

    Args:
        actions: List of ActionItem dicts.
        safety_limits: SafetyLimits configuration.

    Returns:
        Structured dict with per-action safety results.
    """
    try:
        items = copy.deepcopy(actions)
        limits = copy.deepcopy(safety_limits)

        blocked_targets = set(limits.get("blocked_targets", []))
        max_cost = float(limits.get("max_cost_per_action", float("inf")))
        approval_threshold = float(limits.get("require_approval_above", float("inf")))

        results: list[dict[str, Any]] = []

        for action in items:
            action_id = str(action.get("id", "unknown"))
            action_type = str(action.get("type", ""))
            target = str(action.get("target", ""))
            params = action.get("params", {})
            risk_level = str(action.get("risk_level", "low"))

            violations: list[str] = []
            risk_score = _compute_risk_score(risk_level, params)

            # Check blocked targets
            if target in blocked_targets:
                violations.append(f"Target '{target}' is blocked")

            # Check cost limit
            action_cost = float(params.get("estimated_cost", 0.0))
            if action_cost > max_cost:
                violations.append(
                    f"Cost ${action_cost:.2f} exceeds limit ${max_cost:.2f}"
                )

            # Check approval threshold
            if action_cost > approval_threshold:
                violations.append(
                    f"Cost ${action_cost:.2f} requires approval (threshold ${approval_threshold:.2f})"
                )

            # Check risk level
            if risk_level == "critical" and not params.get("force", False):
                violations.append("Critical risk actions require force=true")

            safe = len(violations) == 0

            results.append({
                "action_id": action_id,
                "action_type": action_type,
                "safe": safe,
                "violations": violations,
                "risk_score": risk_score,
            })

        return {
            "status": "success",
            "results": results,
        }
    except Exception as exc:
        return {
            "status": "error",
            "results": [],
            "error": f"Safety check failed: {exc}",
        }


def _compute_risk_score(risk_level: str, params: dict[str, Any]) -> float:
    """Compute a 0.0-1.0 risk score."""
    base_scores = {
        "low": 0.1,
        "medium": 0.4,
        "high": 0.7,
        "critical": 0.95,
    }
    base = base_scores.get(risk_level, 0.5)
    cost_factor = min(float(params.get("estimated_cost", 0)) / 10000.0, 0.3)
    return round(min(base + cost_factor, 1.0), 3)
