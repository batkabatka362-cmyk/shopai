"""Narrative Builder — builds plain-language explanation of the selection decision.

Takes the selection decision output and all engine results, then generates
a human-readable narrative: one-sentence summary, three-paragraph explanation
(what was selected, why it was selected, how it will succeed), and bullet-point
key factors. Template-based — no AI needed.

Returns the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

from typing import Any

from .data import NARRATIVE_TEMPLATES, TRANSITION_PHRASES, FORMATTING_RULES
from .logic import generate_summary, generate_explanation, generate_key_points
from .rules import validate_narrative


def build_narrative(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Build a plain-language narrative explaining the selection decision.

    Args:
        input_payload: dict with keys:
            - selected_product (dict): the chosen product with scores
            - backup_product (dict): runner-up product (optional)
            - decision_rationale (dict): why the product was chosen
            - engine_results (dict): outputs from all upstream engines
            - confidence (dict): confidence assessment
            - goal (str): profit|growth|balanced

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        selected = input_payload.get("selected_product")
        if not selected or not isinstance(selected, dict):
            return _error("selected_product is required")

        rationale = input_payload.get("decision_rationale", {})
        engine_results = input_payload.get("engine_results", {})
        confidence = input_payload.get("confidence", {})
        goal = input_payload.get("goal", "balanced")

        # --- Extract key data points for the narrative ---
        product_name = selected.get("product_name", selected.get("product_id", "Unknown"))
        unified_score = selected.get("unified_score", 0)
        risk_level = _extract_risk_level(selected, engine_results)
        margin = _extract_margin(selected, engine_results)
        demand_score = _extract_demand(selected, engine_results)
        competition_level = _extract_competition(selected, engine_results)
        confidence_level = confidence.get("level", "moderate")

        data_points = {
            "product_name": product_name,
            "unified_score": unified_score,
            "risk_level": risk_level,
            "margin": margin,
            "demand_score": demand_score,
            "competition_level": competition_level,
            "confidence_level": confidence_level,
            "goal": goal,
        }

        # --- Generate narrative components ---
        summary = generate_summary(selected, data_points)
        explanation = generate_explanation(data_points, rationale, engine_results)
        key_points = generate_key_points(selected, data_points, engine_results)

        # --- Assemble full narrative ---
        full_narrative = _assemble_narrative(summary, explanation, key_points)

        # --- Validate narrative against rules ---
        validation = validate_narrative(full_narrative, data_points)
        word_count = len(full_narrative.split())

        return {
            "status": "success",
            "data": {
                "summary": summary,
                "explanation": explanation,
                "key_points": key_points,
                "full_narrative": full_narrative,
                "word_count": word_count,
                "data_points_cited": len(key_points),
                "validation": validation,
            },
            "meta": {
                "module": "narrative_builder",
                "product": product_name,
                "goal": goal,
                "max_words": FORMATTING_RULES["max_word_count"],
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Narrative generation failed: {exc}")


def _extract_risk_level(
    selected: dict[str, Any], engine_results: dict[str, Any],
) -> str:
    """Extract risk level from product data or engine results."""
    risk = selected.get("risk", {}) or {}
    level = risk.get("risk_level")
    if level:
        return level
    composite = risk.get("composite_risk", 0)
    if composite >= 75:
        return "critical"
    if composite >= 55:
        return "high"
    if composite >= 35:
        return "moderate"
    if composite >= 15:
        return "low"
    return "minimal"


def _extract_margin(
    selected: dict[str, Any], engine_results: dict[str, Any],
) -> float:
    """Extract profit margin from product data."""
    profit = selected.get("profitability", {}) or {}
    return profit.get("margin", 0.0)


def _extract_demand(
    selected: dict[str, Any], engine_results: dict[str, Any],
) -> float:
    """Extract demand score from product data."""
    demand = selected.get("demand", {}) or {}
    return demand.get("demand_score", 0.0)


def _extract_competition(
    selected: dict[str, Any], engine_results: dict[str, Any],
) -> str:
    """Extract competition level from product data."""
    comp = selected.get("competition", {}) or {}
    landscape = comp.get("competitive_landscape", "")
    if landscape:
        return landscape
    score = comp.get("competition_score", 50)
    if score >= 75:
        return "low competition"
    if score >= 50:
        return "moderate competition"
    if score >= 25:
        return "high competition"
    return "saturated"


def _assemble_narrative(
    summary: str, explanation: dict[str, str], key_points: list[str],
) -> str:
    """Combine narrative components into a single formatted text."""
    parts = [summary, ""]
    for section in ("what", "why", "how"):
        paragraph = explanation.get(section, "")
        if paragraph:
            parts.append(paragraph)
            parts.append("")

    if key_points:
        parts.append("Key Factors:")
        for point in key_points:
            parts.append(f"  - {point}")

    return "\n".join(parts)


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {"module": "narrative_builder"},
        "error": message,
    }
