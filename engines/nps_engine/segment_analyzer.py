"""NPS Engine — segment analyzer.

Analyzes NPS by customer segment.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def analyze_segments(
    validated_responses: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze NPS scores broken down by customer segment.

    Args:
        validated_responses: Validated NPS responses.
        segments: Segment definitions.

    Returns:
        Structured dict with segment breakdown.
    """
    try:
        # Group responses by segment
        seg_responses: dict[str, list[dict[str, Any]]] = {}
        for resp in validated_responses:
            seg = resp.get("segment", "default")
            seg_responses.setdefault(seg, []).append(resp)

        breakdown: list[dict[str, Any]] = []
        for seg_name, resps in sorted(seg_responses.items()):
            total = len(resps)
            if total == 0:
                continue

            promoters = sum(1 for r in resps if r["score"] >= 9)
            passives = sum(1 for r in resps if 7 <= r["score"] <= 8)
            detractors = sum(1 for r in resps if r["score"] <= 6)

            p_pct = round(promoters / total * 100, 1)
            pa_pct = round(passives / total * 100, 1)
            d_pct = round(detractors / total * 100, 1)

            breakdown.append({
                "segment": seg_name,
                "nps_score": round(p_pct - d_pct, 1),
                "promoters_pct": p_pct,
                "passives_pct": pa_pct,
                "detractors_pct": d_pct,
                "response_count": total,
            })

        return {"status": "success", "segment_breakdown": breakdown}
    except Exception as exc:
        return {"status": "error", "segment_breakdown": [], "error": f"Segment analysis failed: {exc}"}
