"""Risk Disclosure — core logic for risk prioritization and mitigation.

Prioritizes risks by severity, generates actionable mitigation plans,
and calculates worst-case financial scenarios. Every risk gets a
concrete response — no risk is left without a mitigation path.
"""

from __future__ import annotations

from typing import Any

from .data import MITIGATION_LIBRARY, WORST_CASE_FACTORS


# Severity ordering for prioritization
SEVERITY_ORDER: dict[str, int] = {
    "critical": 1,
    "high": 2,
    "moderate": 3,
    "low": 4,
}


def prioritize_risks(risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prioritize risks by severity (critical first) then by score.

    Args:
        risks: List of risk dicts with 'severity' and 'score' keys.

    Returns:
        Sorted list of risks — most severe first.
    """
    if not risks:
        return []

    def sort_key(risk: dict[str, Any]) -> tuple[int, float]:
        severity = risk.get("severity", "low")
        score = risk.get("score", 0)
        return (
            SEVERITY_ORDER.get(severity, 99),
            -score,  # Higher score = more urgent within same severity
        )

    return sorted(risks, key=sort_key)


def generate_mitigation_plan(risk: dict[str, Any]) -> dict[str, Any]:
    """Generate a concrete mitigation plan for a specific risk.

    Looks up the risk ID in the mitigation library for a tailored plan.
    Falls back to severity-based generic mitigation if no specific
    plan exists.

    Args:
        risk: A risk dict with id, name, severity, and description.

    Returns:
        Mitigation plan dict with strategy, actions, timeline, and cost.
    """
    risk_id = risk.get("id", "")
    severity = risk.get("severity", "moderate")

    # Check for a specific mitigation plan
    specific = MITIGATION_LIBRARY.get(risk_id)
    if specific:
        return {
            "strategy": specific["strategy"],
            "actions": specific["actions"],
            "timeline": specific["timeline"],
            "estimated_cost": specific.get("estimated_cost", "minimal"),
            "effectiveness": specific.get("effectiveness", "moderate"),
        }

    # Fall back to severity-based generic mitigation
    return _generic_mitigation(severity, risk)


def _generic_mitigation(
    severity: str, risk: dict[str, Any],
) -> dict[str, Any]:
    """Generate a generic mitigation plan based on severity level."""
    plans: dict[str, dict[str, Any]] = {
        "critical": {
            "strategy": "Immediate risk reduction required before proceeding",
            "actions": [
                "Reduce initial order size by 50% to limit exposure",
                "Set a hard stop-loss: exit if losses exceed 20% of investment",
                "Identify and validate a backup product before committing",
                "Monitor daily for the first 30 days",
            ],
            "timeline": "Before launch — do not proceed without mitigation",
            "estimated_cost": "10-15% of investment for risk reduction measures",
            "effectiveness": "moderate — critical risks cannot be fully eliminated",
        },
        "high": {
            "strategy": "Proactive risk management with regular monitoring",
            "actions": [
                "Start with a smaller test order to validate assumptions",
                "Set weekly review checkpoints for the first month",
                "Prepare a contingency plan if metrics fall below projections",
                "Allocate 10% budget reserve for unexpected costs",
            ],
            "timeline": "Implement before and during launch (weeks 1-4)",
            "estimated_cost": "5-10% of investment",
            "effectiveness": "high — early detection prevents escalation",
        },
        "moderate": {
            "strategy": "Monitor and adjust as needed",
            "actions": [
                "Track key metrics weekly during launch phase",
                "Review pricing strategy if margins drop below projections",
                "Maintain flexibility in inventory commitments",
            ],
            "timeline": "Ongoing during first 60 days",
            "estimated_cost": "minimal — primarily time investment",
            "effectiveness": "high — moderate risks are usually manageable",
        },
        "low": {
            "strategy": "Standard monitoring — no special action required",
            "actions": [
                "Include in regular performance reviews",
                "No additional investment needed for mitigation",
            ],
            "timeline": "Part of normal operations",
            "estimated_cost": "none",
            "effectiveness": "high — low risks rarely materialize",
        },
    }

    plan = plans.get(severity, plans["moderate"])
    return plan


def calculate_worst_case(
    risks: list[dict[str, Any]], investment: float,
) -> dict[str, Any]:
    """Calculate the worst-case financial scenario given identified risks.

    Uses risk severity and scores to estimate the maximum potential loss.
    This is deliberately conservative — worst case means worst case.

    Args:
        risks: List of risk dicts with severity and score.
        investment: The estimated initial investment in dollars.

    Returns:
        Worst-case scenario dict with loss amounts and descriptions.
    """
    if not risks or investment <= 0:
        return {
            "maximum_loss": 0,
            "loss_percentage": 0,
            "scenario_description": "No risks identified or no investment specified.",
            "recovery_time": "N/A",
            "probability": "N/A",
        }

    # Find the highest severity risk
    highest = max(risks, key=lambda r: SEVERITY_ORDER.get(r.get("severity", "low"), 99) * -1)
    highest_severity = highest.get("severity", "low")

    # Get loss factor from reference data
    factor_data = WORST_CASE_FACTORS.get(highest_severity, WORST_CASE_FACTORS["moderate"])
    loss_pct = factor_data["loss_percentage"]
    maximum_loss = round(investment * (loss_pct / 100), 2)

    # Adjust based on number of high/critical risks (compounding effect)
    high_critical_count = sum(
        1 for r in risks if r.get("severity") in ("high", "critical")
    )
    if high_critical_count > 1:
        compounding = min(1.0, loss_pct / 100 + 0.1 * (high_critical_count - 1))
        maximum_loss = round(investment * compounding, 2)
        loss_pct = round(compounding * 100, 1)

    # Cap at 100% of investment
    maximum_loss = min(maximum_loss, investment)
    loss_pct = min(loss_pct, 100.0)

    scenario = factor_data["scenario"].format(
        loss=maximum_loss, investment=investment, pct=loss_pct,
    )

    return {
        "maximum_loss": maximum_loss,
        "loss_percentage": loss_pct,
        "scenario_description": scenario,
        "recovery_time": factor_data.get("recovery_time", "unknown"),
        "probability": factor_data.get("probability", "unknown"),
        "contributing_risks": [r.get("name", "") for r in risks if r.get("severity") in ("high", "critical")],
    }
