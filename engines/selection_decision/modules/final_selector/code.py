"""Final selector engine — makes the definitive product selection.

Main entry point: select_final(input_payload)
Returns engine contract: {status, data, meta, error}

Takes ranked products + confidence + comparison results and produces:
  - #1 pick + #2 backup
  - Decision rationale explaining why
  - Action plan with concrete next steps
  - Expected outcome projections
"""
from __future__ import annotations

import time
from typing import Any

from .data import SELECTION_THRESHOLDS, get_action_plan, get_outcome_benchmark
from .logic import validate_selection, generate_action_plan, calculate_expected_outcome
from .rules import evaluate_selection_rules


def select_final(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Make the final product selection with rationale and action plan.

    Args:
        input_payload: {
            ranked_products: list[dict] — products sorted by unified_score
            confidence: dict             — output from confidence_calculator
            comparison: dict             — output from comparison module
            goal: str                    — profit|growth|balanced
        }

    Returns:
        Engine contract: {status, data, meta, error}
    """
    start = time.time()

    try:
        ranked = input_payload.get("ranked_products", [])
        confidence = input_payload.get("confidence", {})
        comparison = input_payload.get("comparison", {})
        goal = input_payload.get("goal", "balanced")

        if not ranked:
            return _error("ranked_products is required and must be non-empty", start)

        confidence_score = confidence.get("composite_confidence", 50.0)
        confidence_level = confidence.get("classification", {}).get("level", "medium")

        # --- Attempt selection of #1 pick ---
        primary, primary_reason = _select_primary(ranked, confidence_score, comparison)

        # --- Select #2 backup ---
        backup, backup_reason = _select_backup(ranked, primary)

        # --- Validate the selection ---
        validation = validate_selection(primary, {
            "min_confidence": SELECTION_THRESHOLDS["min_confidence"],
            "confidence_score": confidence_score,
            "goal": goal,
        })

        # --- Generate action plan ---
        action_plan = generate_action_plan(primary, confidence_level, goal)

        # --- Calculate expected outcomes ---
        expected = calculate_expected_outcome(
            primary,
            {"confidence_level": confidence_level, "goal": goal},
        )

        # --- Rules evaluation ---
        rules_result = evaluate_selection_rules({
            "product": primary,
            "confidence_score": confidence_score,
            "has_critical_risk": _has_critical_risk(primary),
            "profitability_score": primary.get("normalized_scores", {}).get("profitability", 0),
        })

        # --- Build decision rationale ---
        rationale = _build_rationale(
            primary, backup, confidence_score, comparison, goal,
        )

        data = {
            "selected_product": {
                "product_id": primary.get("product_id"),
                "product_name": primary.get("product_name", primary.get("product_id")),
                "unified_score": primary.get("unified_score", 0),
                "selection_reason": primary_reason,
            },
            "backup_product": {
                "product_id": backup.get("product_id") if backup else None,
                "product_name": backup.get("product_name") if backup else None,
                "unified_score": backup.get("unified_score", 0) if backup else None,
                "backup_reason": backup_reason,
            },
            "decision_rationale": rationale,
            "validation": validation,
            "action_plan": action_plan,
            "expected_outcome": expected,
            "rules": rules_result,
            "confidence_at_selection": {
                "score": confidence_score,
                "level": confidence_level,
            },
        }

        return {
            "status": "success",
            "data": data,
            "meta": {
                "module": "final_selector",
                "duration_ms": round((time.time() - start) * 1000, 2),
                "products_considered": len(ranked),
                "goal": goal,
            },
            "error": None,
        }

    except (ValueError, KeyError, TypeError) as exc:
        return _error(str(exc), start)


def _select_primary(
    ranked: list[dict[str, Any]],
    confidence_score: float,
    comparison: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Select the primary product using score + confidence + risk checks."""
    min_confidence = SELECTION_THRESHOLDS["min_confidence"]

    for product in ranked:
        # Skip products with critical risk
        if _has_critical_risk(product):
            continue

        unified = product.get("unified_score", 0)
        if unified < SELECTION_THRESHOLDS["min_unified_score"]:
            continue

        # If confidence is sufficient, select highest-scoring viable product
        if confidence_score >= min_confidence:
            reason = (
                f"Highest scoring product ({unified:.1f}) with acceptable "
                f"confidence ({confidence_score:.0f}%) and no critical risks"
            )
            return product, reason

        # Low confidence — still select but flag it
        reason = (
            f"Top-scored product ({unified:.1f}) but confidence is low "
            f"({confidence_score:.0f}%). Human review recommended."
        )
        return product, reason

    # Fallback: return top product even with issues
    product = ranked[0]
    reason = "Selected by default — all products have concerns. Review carefully."
    return product, reason


def _select_backup(
    ranked: list[dict[str, Any]],
    primary: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    """Select the backup product (different from primary)."""
    primary_id = primary.get("product_id")
    min_ratio = SELECTION_THRESHOLDS["backup_min_score_ratio"]
    primary_score = primary.get("unified_score", 1)

    for product in ranked:
        if product.get("product_id") == primary_id:
            continue
        backup_score = product.get("unified_score", 0)
        if primary_score > 0 and backup_score / primary_score >= min_ratio:
            reason = (
                f"Best alternative ({backup_score:.1f}) — "
                f"{backup_score / primary_score * 100:.0f}% of primary score"
            )
            return product, reason

    # No viable backup
    if len(ranked) > 1:
        fallback = [p for p in ranked if p.get("product_id") != primary_id]
        if fallback:
            return fallback[0], "Only available alternative (score ratio below threshold)"
    return None, "No viable backup product available"


def _has_critical_risk(product: dict[str, Any]) -> bool:
    """Check if a product has critical-level risk."""
    risk_data = product.get("risk", {})
    risk_level = risk_data.get("risk_level", "").lower() if isinstance(risk_data, dict) else ""
    return risk_level == "critical"


def _build_rationale(
    primary: dict[str, Any],
    backup: dict[str, Any] | None,
    confidence: float,
    comparison: dict[str, Any],
    goal: str,
) -> dict[str, Any]:
    """Build a human-readable decision rationale."""
    pid = primary.get("product_id", "unknown")
    score = primary.get("unified_score", 0)

    factors: list[str] = [f"Unified score: {score:.1f}/100"]

    # Add comparison insights
    best_for = comparison.get("best_for_goal", {})
    if best_for.get("best_product_id") == pid:
        factors.append(f"Best product for {goal} goal (goal-weighted: {best_for.get('goal_score', 0):.0f})")

    profiles = comparison.get("product_profiles", [])
    for profile in profiles:
        if profile.get("product_id") == pid:
            factors.append(f"Wins {profile.get('dimensions_won', 0)} dimensions")
            if profile.get("critical_weaknesses"):
                factors.append(f"Weaknesses: {', '.join(profile['critical_weaknesses'])}")
            break

    factors.append(f"Confidence: {confidence:.0f}%")

    return {
        "summary": f"{pid} selected with {score:.1f}/100 score at {confidence:.0f}% confidence",
        "factors": factors,
        "goal": goal,
        "alternative": backup.get("product_id") if backup else None,
    }


def _error(message: str, start: float) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {
            "module": "final_selector",
            "duration_ms": round((time.time() - start) * 1000, 2),
        },
        "error": {"type": "SelectionError", "message": message},
    }
