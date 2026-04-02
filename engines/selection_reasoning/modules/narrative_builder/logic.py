"""Decision functions for narrative construction.

Provides summary generation, multi-paragraph explanation assembly,
and key-point extraction from engine scores and results.
"""

from __future__ import annotations

from typing import Any

from .data import (
    NARRATIVE_TEMPLATES,
    TRANSITION_PHRASES,
    SCORE_DESCRIPTORS,
    RISK_DESCRIPTORS,
    CONFIDENCE_DESCRIPTORS,
)


def generate_summary(selection: dict[str, Any]) -> str:
    """Generate a one-sentence summary of the selection decision.

    Args:
        selection: dict with product_name, score, goal, confidence_level, risk_level.

    Returns:
        A concise one-sentence summary string.
    """
    product_name = selection.get("product_name", "Unknown Product")
    score = selection.get("score", 0)
    goal = selection.get("goal", "balanced")
    confidence_level = selection.get("confidence_level", "moderate")
    risk_level = selection.get("risk_level", "moderate")

    score_desc = _get_score_descriptor(score)
    risk_desc = RISK_DESCRIPTORS.get(risk_level, "moderate risk")
    conf_desc = CONFIDENCE_DESCRIPTORS.get(confidence_level, "moderate confidence")

    template = NARRATIVE_TEMPLATES["summary"].get(goal, NARRATIVE_TEMPLATES["summary"]["balanced"])

    return template.format(
        product_name=product_name,
        score=score,
        score_desc=score_desc,
        risk_desc=risk_desc,
        conf_desc=conf_desc,
    )


def generate_explanation(factors: dict[str, Any]) -> dict[str, str]:
    """Generate a three-paragraph explanation: what, why, how.

    Args:
        factors: dict with product_name, score, goal, engine_results,
                 risk_level, confidence, alternatives_count.

    Returns:
        Dict with keys 'what', 'why', 'how' mapping to paragraph strings.
    """
    product_name = factors.get("product_name", "Unknown Product")
    score = factors.get("score", 0)
    goal = factors.get("goal", "balanced")
    engine_results = factors.get("engine_results", {})
    risk_level = factors.get("risk_level", "moderate")
    confidence = factors.get("confidence", {})
    alt_count = factors.get("alternatives_count", 0)

    # --- WHAT paragraph ---
    what_template = NARRATIVE_TEMPLATES["what"]
    profitability = engine_results.get("profitability", {})
    demand = engine_results.get("demand", {})
    margin = profitability.get("margin", 0)
    demand_score = demand.get("demand_score", 0)

    what_paragraph = what_template.format(
        product_name=product_name,
        score=score,
        alt_count=alt_count,
        margin=margin,
        demand_score=demand_score,
    )

    # --- WHY paragraph ---
    why_template = NARRATIVE_TEMPLATES["why"].get(goal, NARRATIVE_TEMPLATES["why"]["balanced"])
    transition = TRANSITION_PHRASES["why"]
    risk_desc = RISK_DESCRIPTORS.get(risk_level, "moderate risk")
    confidence_level = confidence.get("level", "moderate")
    conf_desc = CONFIDENCE_DESCRIPTORS.get(confidence_level, "moderate confidence")

    why_paragraph = f"{transition} {why_template.format(product_name=product_name, score=score, risk_desc=risk_desc, conf_desc=conf_desc, margin=margin)}"

    # --- HOW paragraph ---
    how_template = NARRATIVE_TEMPLATES["how"]
    engines_used = [k for k, v in engine_results.items() if v]
    engine_count = len(engines_used)
    conf_coverage = confidence.get("coverage", 0)

    how_paragraph = how_template.format(
        product_name=product_name,
        engine_count=engine_count,
        coverage=round(conf_coverage * 100),
        risk_level=risk_level,
    )

    return {
        "what": what_paragraph,
        "why": why_paragraph,
        "how": how_paragraph,
    }


def generate_key_points(scores: dict[str, Any]) -> list[dict[str, str]]:
    """Extract bullet-point key factors from engine scores.

    Args:
        scores: dict with score, engine_results, risk_level, confidence, goal.

    Returns:
        List of dicts with 'label' and 'value' keys.
    """
    points: list[dict[str, str]] = []
    engine_results = scores.get("engine_results", {})
    risk_level = scores.get("risk_level", "unknown")
    confidence = scores.get("confidence", {})
    unified_score = scores.get("score", 0)
    goal = scores.get("goal", "balanced")

    # Unified score
    points.append({
        "label": "Overall Score",
        "value": f"{unified_score}/100 ({_get_score_descriptor(unified_score)})",
    })

    # Profitability
    profit_data = engine_results.get("profitability", {})
    if profit_data:
        margin = profit_data.get("margin", 0)
        roi = profit_data.get("roi", 0)
        points.append({
            "label": "Profitability",
            "value": f"{margin}% margin, {roi}% projected ROI",
        })

    # Demand
    demand_data = engine_results.get("demand", {})
    if demand_data:
        volume = demand_data.get("volume_projection", 0)
        d_score = demand_data.get("demand_score", 0)
        points.append({
            "label": "Market Demand",
            "value": f"Score {d_score}/100, ~{volume} units/month projected",
        })

    # Competition
    comp_data = engine_results.get("competition", {})
    if comp_data:
        landscape = comp_data.get("competitive_landscape", "unknown")
        c_score = comp_data.get("competition_score", 0)
        points.append({
            "label": "Competition",
            "value": f"{landscape} landscape (score: {c_score}/100)",
        })

    # Risk — always included
    points.append({
        "label": "Risk Level",
        "value": RISK_DESCRIPTORS.get(risk_level, f"{risk_level} risk"),
    })

    # Confidence
    conf_level = confidence.get("level", "unknown")
    conf_coverage = confidence.get("coverage", 0)
    points.append({
        "label": "Decision Confidence",
        "value": f"{conf_level} ({round(conf_coverage * 100)}% data coverage)",
    })

    # Goal alignment
    points.append({
        "label": "Business Goal",
        "value": f"Optimized for {goal}",
    })

    return points


def _get_score_descriptor(score: float) -> str:
    """Map a numeric score to a human-readable descriptor."""
    for threshold, descriptor in sorted(SCORE_DESCRIPTORS.items(), reverse=True):
        if score >= threshold:
            return descriptor
    return "very weak"
