"""Customer Support Engine — resolution finder.

Find resolution from knowledge base for classified tickets.
"""
from __future__ import annotations

import copy
from typing import Any


def find_resolutions(
    **kwargs: Any,
) -> dict[str, Any]:
    """Find resolutions for classified tickets.

    Args:
        **kwargs: Must include classified tickets and 'resolutions' knowledge base.

    Returns:
        Structured dict with suggested resolutions.
    """
    try:
        class_data = kwargs.get("ticket_classifier_data", {})
        classified = class_data.get("classified_tickets", [])
        resolutions_kb = copy.deepcopy(kwargs.get("resolutions", []))

        # Build resolution lookup by category
        kb_by_category: dict[str, list] = {}
        for res in resolutions_kb:
            cat = str(res.get("category", "general"))
            kb_by_category.setdefault(cat, []).append(res)

        suggestions: list[dict[str, Any]] = []

        for ticket in classified:
            tid = ticket.get("ticket_id", "unknown")
            category = ticket.get("category", "general")
            matching_resolutions = kb_by_category.get(category, [])

            if matching_resolutions:
                best = matching_resolutions[0]
                suggestions.append({
                    "ticket_id": tid,
                    "suggested_resolution": best.get("resolution", ""),
                    "confidence": round(min(0.5 + len(matching_resolutions) * 0.1, 0.95), 2),
                    "source": "knowledge_base",
                    "category": category,
                })
            else:
                suggestions.append({
                    "ticket_id": tid,
                    "suggested_resolution": "Escalate to human agent",
                    "confidence": 0.0,
                    "source": "fallback",
                    "category": category,
                })

        return {
            "status": "success",
            "result": {"suggested_resolutions": suggestions},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Resolution finding failed: {exc}"}
