"""Final selector decision logic — validation, action plans, outcome projections.

Translates the raw selection into validated, actionable output with
concrete next steps and realistic expected outcomes.
"""
from __future__ import annotations

from typing import Any

from .data import (
    SELECTION_THRESHOLDS,
    get_action_plan,
    get_outcome_benchmark,
)


def validate_selection(
    product: dict[str, Any],
    constraints: dict[str, Any],
) -> dict[str, Any]:
    """Validate that the selected product meets all selection constraints.

    Args:
        product: The selected product dict with unified_score, normalized_scores, etc.
        constraints: {
            min_confidence: float,
            confidence_score: float,
            goal: str,
        }

    Returns:
        {valid: bool, issues: list[str], passed_gates: list[str]}
    """
    issues: list[str] = []
    passed_gates: list[str] = []
    scores = product.get("normalized_scores", {})
    unified = product.get("unified_score", 0)

    # Gate 1: Minimum unified score
    min_score = SELECTION_THRESHOLDS["min_unified_score"]
    if unified >= min_score:
        passed_gates.append(f"Unified score ({unified:.1f}) >= {min_score}")
    else:
        issues.append(f"Unified score ({unified:.1f}) below minimum ({min_score})")

    # Gate 2: Confidence threshold
    confidence = constraints.get("confidence_score", 0)
    min_conf = constraints.get("min_confidence", SELECTION_THRESHOLDS["min_confidence"])
    if confidence >= min_conf:
        passed_gates.append(f"Confidence ({confidence:.0f}%) >= {min_conf:.0f}%")
    else:
        issues.append(f"Confidence ({confidence:.0f}%) below minimum ({min_conf:.0f}%)")

    # Gate 3: No critical risk
    risk_data = product.get("risk", {})
    risk_level = risk_data.get("risk_level", "unknown") if isinstance(risk_data, dict) else "unknown"
    risk_order = SELECTION_THRESHOLDS["risk_level_order"]
    max_risk = SELECTION_THRESHOLDS["max_risk_level"]

    if risk_level.lower() in risk_order:
        risk_idx = risk_order.index(risk_level.lower())
        max_idx = risk_order.index(max_risk)
        if risk_idx <= max_idx:
            passed_gates.append(f"Risk level ({risk_level}) within acceptable range")
        else:
            issues.append(f"Risk level ({risk_level}) exceeds maximum ({max_risk})")
    else:
        passed_gates.append("Risk level unknown — proceeding with caution")

    # Gate 4: Positive profitability
    profit_score = scores.get("profitability")
    min_profit = SELECTION_THRESHOLDS["min_profitability_score"]
    if profit_score is not None and profit_score >= min_profit:
        passed_gates.append(f"Profitability score ({profit_score:.0f}) >= {min_profit}")
    elif profit_score is not None:
        issues.append(f"Profitability score ({profit_score:.0f}) below minimum ({min_profit})")
    else:
        issues.append("Profitability data missing — cannot validate margin")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "passed_gates": passed_gates,
        "gates_checked": len(passed_gates) + len(issues),
    }


def generate_action_plan(
    product: dict[str, Any],
    confidence_level: str,
    goal: str,
) -> dict[str, Any]:
    """Generate a concrete action plan for the selected product.

    Args:
        product: Selected product dict.
        confidence_level: 'high', 'medium', or 'low'.
        goal: Business goal — 'profit', 'growth', or 'balanced'.

    Returns:
        Action plan dict with steps, timeline, and budget allocation.
    """
    template = get_action_plan(confidence_level)
    pid = product.get("product_id", "unknown")
    unified = product.get("unified_score", 0)

    # Customize steps based on goal
    goal_additions: dict[str, list[str]] = {
        "profit": [
            "Focus on margin optimization — negotiate supplier pricing before ordering",
            "Set minimum ROAS threshold at 3.0x before scaling",
        ],
        "growth": [
            "Prioritize rapid market penetration — accept lower initial margins",
            "Invest in content and SEO from day 1 for organic growth",
        ],
        "balanced": [
            "Balance ad spend with organic acquisition from the start",
            "Target ROAS of 2.5x with gradual scaling",
        ],
    }

    steps = list(template["steps"])
    steps.extend(goal_additions.get(goal, goal_additions["balanced"]))

    return {
        "product_id": pid,
        "plan_type": template["label"],
        "confidence_level": confidence_level,
        "steps": steps,
        "timeline": template["timeline"],
        "budget_allocation": template["budget_allocation"],
        "goal_specific_notes": f"Optimized for {goal} goal",
        "first_milestone": _get_first_milestone(confidence_level, unified),
    }


def calculate_expected_outcome(
    product: dict[str, Any],
    projections: dict[str, Any],
) -> dict[str, Any]:
    """Calculate expected outcomes for the selected product.

    Args:
        product: Selected product dict with unified_score.
        projections: {confidence_level: str, goal: str}

    Returns:
        Expected outcome projections with ranges and caveats.
    """
    unified = product.get("unified_score", 0)
    benchmark = get_outcome_benchmark(unified)
    confidence_level = projections.get("confidence_level", "medium")

    # Adjust expectations based on confidence
    confidence_modifier = {"high": 1.0, "medium": 0.8, "low": 0.6}.get(
        confidence_level, 0.7
    )

    revenue_lo, revenue_hi = benchmark["typical_monthly_revenue"]
    roas_lo, roas_hi = benchmark["typical_roas"]
    margin_lo, margin_hi = benchmark["typical_margin"]

    return {
        "tier": benchmark["tier"],
        "success_probability": round(benchmark["expected_success_rate"] * confidence_modifier, 2),
        "monthly_revenue_range": {
            "low": round(revenue_lo * confidence_modifier),
            "high": round(revenue_hi * confidence_modifier),
        },
        "expected_roas": {
            "low": round(roas_lo * confidence_modifier, 1),
            "high": round(roas_hi * confidence_modifier, 1),
        },
        "expected_margin_pct": {
            "low": round(margin_lo * confidence_modifier, 1),
            "high": round(margin_hi * confidence_modifier, 1),
        },
        "time_to_profitability": benchmark["time_to_profitability"],
        "confidence_adjustment": confidence_modifier,
        "caveats": [
            "Projections based on historical benchmarks — actual results vary",
            "Execution quality is the biggest variable not captured in scores",
            f"Confidence modifier of {confidence_modifier:.0%} applied to all ranges",
        ],
    }


def _get_first_milestone(confidence_level: str, score: float) -> dict[str, str]:
    """Determine the first milestone to track after selection."""
    if confidence_level == "high":
        return {
            "metric": "First 10 sales",
            "target_timeline": "7 days",
            "action_if_missed": "Review ad targeting and product listing quality",
        }
    elif confidence_level == "medium":
        return {
            "metric": "First 5 sales",
            "target_timeline": "10 days",
            "action_if_missed": "Evaluate if product-market fit exists before spending more",
        }
    else:
        return {
            "metric": "50 landing page visits with > 5% email capture",
            "target_timeline": "14 days",
            "action_if_missed": "Pivot to backup product — insufficient demand signal",
        }
