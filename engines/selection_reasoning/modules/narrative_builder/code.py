"""Main narrative builder engine.

Builds a plain-language narrative that explains the product selection
decision. Template-based — no AI required.
Returns the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

from typing import Any

from .logic import generate_summary, generate_explanation, generate_key_points
from .rules import validate_narrative
from .data import FORMATTING_RULES


def build_narrative(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Build a complete narrative explaining the selection decision.

    Args:
        input_payload: dict with keys:
            - selected_product (dict): the chosen product with scores
            - selection_score (float): unified score of selected product
            - goal (str): profit|growth|balanced
            - engine_results (dict): results from all upstream engines
            - risk_level (str): overall risk assessment
            - confidence (dict): confidence assessment data
            - alternatives (list[dict]): other products considered

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        selected = input_payload.get("selected_product", {})
        if not selected:
            return _error("No selected product provided")

        score = input_payload.get("selection_score", 0)
        goal = input_payload.get("goal", "balanced")
        engine_results = input_payload.get("engine_results", {})
        risk_level = input_payload.get("risk_level", "unknown")
        confidence = input_payload.get("confidence", {})
        alternatives = input_payload.get("alternatives", [])

        product_name = selected.get("product_name", selected.get("product_id", "Unknown"))

        # --- Generate the three narrative components ---
        summary = generate_summary({
            "product_name": product_name,
            "score": score,
            "goal": goal,
            "confidence_level": confidence.get("level", "moderate"),
            "risk_level": risk_level,
        })

        explanation = generate_explanation({
            "product_name": product_name,
            "score": score,
            "goal": goal,
            "engine_results": engine_results,
            "risk_level": risk_level,
            "confidence": confidence,
            "alternatives_count": len(alternatives),
        })

        key_points = generate_key_points({
            "score": score,
            "engine_results": engine_results,
            "risk_level": risk_level,
            "confidence": confidence,
            "goal": goal,
        })

        # --- Assemble the full narrative ---
        full_narrative = _assemble_narrative(summary, explanation, key_points)

        # --- Validate against rules ---
        validation = validate_narrative(full_narrative, key_points)

        # --- Enforce word limit ---
        max_words = FORMATTING_RULES["max_words"]
        word_count = len(full_narrative.split())
        if word_count > max_words:
            full_narrative = " ".join(full_narrative.split()[:max_words]) + "..."

        return {
            "status": "success",
            "data": {
                "summary": summary,
                "explanation": explanation,
                "key_points": key_points,
                "full_narrative": full_narrative,
                "word_count": len(full_narrative.split()),
                "validation": validation,
            },
            "meta": {
                "module": "narrative_builder",
                "product": product_name,
                "goal": goal,
                "template_based": True,
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Narrative generation failed: {exc}")


def _assemble_narrative(
    summary: str,
    explanation: dict[str, str],
    key_points: list[dict[str, str]],
) -> str:
    """Combine summary, explanation paragraphs, and key points into one narrative."""
    parts: list[str] = []

    # Lead with the conclusion
    parts.append(summary)
    parts.append("")

    # Three explanation paragraphs
    for section in ("what", "why", "how"):
        paragraph = explanation.get(section, "")
        if paragraph:
            parts.append(paragraph)
            parts.append("")

    # Bullet-point key factors
    if key_points:
        parts.append("Key Factors:")
        for point in key_points:
            label = point.get("label", "")
            value = point.get("value", "")
            parts.append(f"  - {label}: {value}")

    return "\n".join(parts).strip()


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {"module": "narrative_builder"},
        "error": message,
    }
