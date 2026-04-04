"""Selection Reasoning Engine — narrative builder.

Builds a human-readable narrative explaining why each product
was selected or rejected.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def build_narratives(
    decisions: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build narratives for each decision.

    Args:
        decisions: List of decision record dicts.
        evidence: List of evidence item dicts.

    Returns:
        Structured dict with per-product narratives.
    """
    try:
        evidence_map: dict[str, list[dict[str, Any]]] = {}
        for e in evidence:
            pid = str(e.get("product_id", ""))
            if pid:
                evidence_map.setdefault(pid, []).append(e)

        narratives: list[dict[str, Any]] = []

        for decision in decisions:
            pid = str(decision.get("product_id", "unknown"))
            title = str(decision.get("title", pid))
            verdict = str(decision.get("verdict", "unknown"))
            confidence = float(decision.get("confidence", 0.0))
            reasons = decision.get("reasons", [])
            prod_evidence = evidence_map.get(pid, [])

            # Build narrative
            if verdict == "selected":
                tone = "positive"
                opening = f"{title} was selected for the portfolio."
            else:
                tone = "neutral"
                opening = f"{title} was not selected for the portfolio."

            key_points = list(reasons[:3])

            # Add evidence-based points
            for ev in prod_evidence[:2]:
                metric = str(ev.get("metric", ""))
                interpretation = str(ev.get("interpretation", ""))
                if interpretation:
                    key_points.append(f"{metric}: {interpretation}")

            reason_text = " ".join(reasons) if reasons else "No specific reasons recorded."
            narrative = f"{opening} {reason_text}"

            if confidence > 0.8:
                narrative += " This assessment has high confidence."
            elif confidence < 0.5:
                narrative += " Note: this assessment has limited confidence due to data gaps."

            narratives.append({
                "product_id": pid,
                "narrative": narrative,
                "tone": tone,
                "key_points": key_points,
            })

        return {"status": "success", "narratives": narratives}
    except Exception as exc:
        return {"status": "error", "narratives": [], "error": f"Narrative building failed: {exc}"}
