"""Narrative Builder — core logic for generating narrative components.

Generates the summary, explanation paragraphs (what/why/how), and
bullet-point key factors from structured decision data. Uses templates
from data.py to keep narratives consistent and readable.
"""

from __future__ import annotations

from typing import Any

from .data import NARRATIVE_TEMPLATES, TRANSITION_PHRASES


def generate_summary(
    selection: dict[str, Any], data_points: dict[str, Any],
) -> str:
    """Generate a one-sentence summary of the selection decision.

    Args:
        selection: The selected product dict with scores.
        data_points: Extracted data points (product_name, unified_score, etc.).

    Returns:
        A single summary sentence.
    """
    product_name = data_points.get("product_name", "Unknown Product")
    unified_score = data_points.get("unified_score", 0)
    goal = data_points.get("goal", "balanced")
    confidence_level = data_points.get("confidence_level", "moderate")

    # Pick template based on score tier
    if unified_score >= 75:
        template = NARRATIVE_TEMPLATES["summary"]["strong_pick"]
    elif unified_score >= 55:
        template = NARRATIVE_TEMPLATES["summary"]["solid_pick"]
    elif unified_score >= 40:
        template = NARRATIVE_TEMPLATES["summary"]["cautious_pick"]
    else:
        template = NARRATIVE_TEMPLATES["summary"]["weak_pick"]

    return template.format(
        product_name=product_name,
        score=unified_score,
        goal=goal,
        confidence=confidence_level,
    )


def generate_explanation(
    data_points: dict[str, Any],
    rationale: dict[str, Any],
    engine_results: dict[str, Any],
) -> dict[str, str]:
    """Generate a three-paragraph explanation: what, why, how.

    Args:
        data_points: Extracted data points from the decision.
        rationale: Decision rationale from the selection engine.
        engine_results: Outputs from all upstream engines.

    Returns:
        Dict with keys 'what', 'why', 'how' — each a paragraph string.
    """
    product_name = data_points.get("product_name", "Unknown Product")
    unified_score = data_points.get("unified_score", 0)
    margin = data_points.get("margin", 0)
    demand_score = data_points.get("demand_score", 0)
    risk_level = data_points.get("risk_level", "unknown")
    competition_level = data_points.get("competition_level", "unknown")
    goal = data_points.get("goal", "balanced")
    confidence_level = data_points.get("confidence_level", "moderate")

    # --- What: describe what was selected ---
    what_template = NARRATIVE_TEMPLATES["explanation"]["what"]
    what_paragraph = what_template.format(
        product_name=product_name,
        score=unified_score,
        margin=margin,
        demand_score=demand_score,
        competition_level=competition_level,
    )

    # --- Why: explain the reasoning ---
    why_parts = []
    primary_reason = rationale.get("primary_reason", "")
    if primary_reason:
        why_parts.append(primary_reason)
    else:
        why_parts.append(
            f"This product was selected because it best aligns with the "
            f"'{goal}' strategy."
        )

    transition = TRANSITION_PHRASES["supporting"]
    why_parts.append(
        f"{transition} the product demonstrates a {margin:.1f}% margin "
        f"with {competition_level}, indicating sustainable profitability."
    )

    if risk_level in ("low", "minimal"):
        why_parts.append(
            f"The risk profile is {risk_level}, which means the downside "
            f"is well-contained."
        )
    else:
        why_parts.append(
            f"The risk level is {risk_level}, which has been factored "
            f"into the overall score and should be monitored."
        )

    why_paragraph = " ".join(why_parts)

    # --- How: outline the path to success ---
    how_parts = []
    how_parts.append(
        f"To succeed with {product_name}, focus on the factors that drove "
        f"its high score."
    )

    if demand_score >= 60:
        how_parts.append(
            f"Demand is strong (score: {demand_score:.0f}/100), so the market "
            f"is ready for this product."
        )
    else:
        how_parts.append(
            f"Demand is moderate (score: {demand_score:.0f}/100), so marketing "
            f"investment will be needed to build traction."
        )

    how_parts.append(
        f"Confidence in this recommendation is {confidence_level}. "
        f"Monitor actual performance against projections weekly and be "
        f"prepared to pivot if early metrics underperform."
    )

    how_paragraph = " ".join(how_parts)

    return {
        "what": what_paragraph,
        "why": why_paragraph,
        "how": how_paragraph,
    }


def generate_key_points(
    selection: dict[str, Any],
    data_points: dict[str, Any],
    engine_results: dict[str, Any],
) -> list[str]:
    """Generate bullet-point key factors supporting the decision.

    Args:
        selection: The selected product dict.
        data_points: Extracted data points.
        engine_results: All upstream engine outputs.

    Returns:
        List of key factor strings (at least 3).
    """
    points: list[str] = []
    product_name = data_points.get("product_name", "Unknown")
    unified_score = data_points.get("unified_score", 0)
    margin = data_points.get("margin", 0)
    demand_score = data_points.get("demand_score", 0)
    risk_level = data_points.get("risk_level", "unknown")
    competition_level = data_points.get("competition_level", "unknown")
    confidence_level = data_points.get("confidence_level", "moderate")
    goal = data_points.get("goal", "balanced")

    # Always include score
    points.append(f"Unified score: {unified_score:.1f}/100 ({_score_tier(unified_score)})")

    # Include margin if available
    if margin > 0:
        points.append(f"Profit margin: {margin:.1f}% — {'strong' if margin >= 30 else 'adequate'} profitability")

    # Include demand
    if demand_score > 0:
        demand_label = "high" if demand_score >= 70 else "moderate" if demand_score >= 40 else "low"
        points.append(f"Demand: {demand_label} ({demand_score:.0f}/100)")

    # Always include risk
    points.append(f"Risk level: {risk_level} — factored into score as a multiplier")

    # Include competition
    points.append(f"Competition: {competition_level}")

    # Include goal alignment
    points.append(f"Goal alignment: optimized for '{goal}' strategy")

    # Include confidence
    points.append(f"Decision confidence: {confidence_level}")

    return points


def _score_tier(score: float) -> str:
    """Classify a unified score into a human-readable tier."""
    if score >= 75:
        return "excellent"
    if score >= 55:
        return "good"
    if score >= 40:
        return "marginal"
    return "weak"
