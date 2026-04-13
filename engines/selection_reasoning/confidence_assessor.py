"""Selection Reasoning Engine — confidence assessor.

Assesses overall confidence in each product's reasoning based on
data quality, evidence strength, and reasoning consistency.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def assess_confidence(
    decisions: list[dict[str, Any]],
    compilations: list[dict[str, Any]],
    narratives: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess confidence for each product's reasoning.

    Args:
        decisions: List of decision record dicts.
        compilations: Per-product evidence compilations.
        narratives: Per-product narratives.

    Returns:
        Structured dict with per-product confidence assessments.
    """
    try:
        comp_map = {str(c.get("product_id", "")): c for c in compilations}
        narr_map = {str(n.get("product_id", "")): n for n in narratives}

        assessments: list[dict[str, Any]] = []

        for decision in decisions:
            pid = str(decision.get("product_id", "unknown"))
            decision_confidence = float(decision.get("confidence", 0.0))
            comp = comp_map.get(pid, {})
            narr = narr_map.get(pid, {})

            evidence_strength = float(comp.get("evidence_strength", 0.0))
            gaps = comp.get("gaps", [])
            key_points = narr.get("key_points", [])

            # Data quality: based on evidence strength and gaps
            data_quality = round(evidence_strength * (1 - len(gaps) * 0.1), 3)
            data_quality = max(0.0, min(data_quality, 1.0))

            # Reasoning strength: based on number of key points and decision confidence
            reasoning_points = min(len(key_points) / 3.0, 1.0)
            reasoning_strength = round(
                decision_confidence * 0.5 + reasoning_points * 0.5, 3,
            )

            # Overall confidence
            overall = round(
                data_quality * 0.4 + reasoning_strength * 0.4 + decision_confidence * 0.2, 3,
            )

            caveats: list[str] = []
            if data_quality < 0.5:
                caveats.append("Limited data quality may affect accuracy")
            if gaps:
                caveats.append(f"Missing evidence from: {', '.join(gaps[:3])}")
            if decision_confidence < 0.6:
                caveats.append("Decision confidence is below threshold")

            assessments.append({
                "product_id": pid,
                "overall_confidence": overall,
                "data_quality": data_quality,
                "reasoning_strength": reasoning_strength,
                "caveats": caveats,
            })

        return {"status": "success", "assessments": assessments}
    except Exception as exc:
        return {"status": "error", "assessments": [], "error": f"Confidence assessment failed: {exc}"}
