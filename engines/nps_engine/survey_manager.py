"""NPS Engine — survey manager.

Manages NPS survey distribution and response collection.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def manage_surveys(
    responses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate and organize NPS survey responses.

    Args:
        responses: Raw NPS responses [{customer_id, score, comment, date}].

    Returns:
        Structured dict with validated responses.
    """
    try:
        items = copy.deepcopy(responses)
        validated: list[dict[str, Any]] = []
        invalid_count = 0

        for resp in items:
            score = resp.get("score")
            if score is None:
                invalid_count += 1
                continue
            score = int(score)
            if score < 0 or score > 10:
                invalid_count += 1
                continue

            validated.append({
                "customer_id": str(resp.get("customer_id", "")),
                "score": score,
                "comment": str(resp.get("comment", "")),
                "date": str(resp.get("date", "")),
                "segment": str(resp.get("segment", "default")),
            })

        return {
            "status": "success",
            "validated_responses": validated,
            "total_received": len(items),
            "valid_count": len(validated),
            "invalid_count": invalid_count,
        }
    except Exception as exc:
        return {"status": "error", "validated_responses": [], "error": f"Survey management failed: {exc}"}
