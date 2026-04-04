"""NPS Engine — score calculator.

Calculates NPS from responses: promoters percentage minus detractors percentage.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def calculate_score(
    validated_responses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate NPS score from validated responses.

    NPS = % Promoters (9-10) - % Detractors (0-6). Passives = 7-8.

    Args:
        validated_responses: Validated NPS responses.

    Returns:
        Structured dict with NPS score breakdown.
    """
    try:
        total = len(validated_responses)
        if total == 0:
            return {
                "status": "success",
                "nps_score": 0.0,
                "promoters_pct": 0.0,
                "passives_pct": 0.0,
                "detractors_pct": 0.0,
            }

        promoters = sum(1 for r in validated_responses if r["score"] >= 9)
        passives = sum(1 for r in validated_responses if 7 <= r["score"] <= 8)
        detractors = sum(1 for r in validated_responses if r["score"] <= 6)

        promoters_pct = round(promoters / total * 100, 1)
        passives_pct = round(passives / total * 100, 1)
        detractors_pct = round(detractors / total * 100, 1)
        nps_score = round(promoters_pct - detractors_pct, 1)

        return {
            "status": "success",
            "nps_score": nps_score,
            "promoters_pct": promoters_pct,
            "passives_pct": passives_pct,
            "detractors_pct": detractors_pct,
        }
    except Exception as exc:
        return {"status": "error", "nps_score": 0.0, "error": f"Score calculation failed: {exc}"}
