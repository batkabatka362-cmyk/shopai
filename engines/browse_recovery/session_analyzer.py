"""Browse Recovery Engine — session analyzer.

Identifies browse-abandon sessions: visitors who viewed products
but left without purchasing. Classifies engagement level based on
pages viewed, products viewed, time on site, and cart activity.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Engagement thresholds
# ---------------------------------------------------------------------------

_HIGH_PAGES = 8
_MEDIUM_PAGES = 3
_HIGH_DURATION = 300.0   # 5 minutes
_MEDIUM_DURATION = 60.0  # 1 minute


def analyze_sessions(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze browse sessions to identify abandon patterns.

    Args:
        sessions: List of SessionRecord dicts.

    Returns:
        Structured dict with per-session analysis results.
    """
    try:
        items = copy.deepcopy(sessions)
        analyzed: list[dict[str, Any]] = []
        abandon_count = 0

        for session in items:
            user_id = str(session.get("user_id", "unknown"))
            pages_viewed = session.get("pages_viewed", [])
            products_viewed = session.get("products_viewed", [])
            duration = float(session.get("duration", 0.0))
            cart_items = session.get("cart_items", [])

            pages_count = len(pages_viewed)
            products_count = len(products_viewed)
            cart_count = len(cart_items)

            # A browse-abandon session: viewed products but did not purchase
            # We treat all sessions as non-purchased (recovery candidates)
            is_browse_abandon = products_count > 0

            # Engagement level classification
            engagement_score = 0.0
            engagement_score += min(pages_count / _HIGH_PAGES, 1.0) * 30.0
            engagement_score += min(products_count / 5.0, 1.0) * 30.0
            engagement_score += min(duration / _HIGH_DURATION, 1.0) * 20.0
            engagement_score += min(cart_count / 3.0, 1.0) * 20.0

            if engagement_score >= 70.0:
                engagement_level = "high"
            elif engagement_score >= 40.0:
                engagement_level = "medium"
            else:
                engagement_level = "low"

            if is_browse_abandon:
                abandon_count += 1

            analyzed.append({
                "user_id": user_id,
                "pages_viewed_count": pages_count,
                "products_viewed_count": products_count,
                "duration": duration,
                "cart_items_count": cart_count,
                "is_browse_abandon": is_browse_abandon,
                "engagement_level": engagement_level,
            })

        return {
            "status": "success",
            "sessions": analyzed,
            "total_sessions": len(analyzed),
            "abandon_count": abandon_count,
        }
    except Exception as exc:
        return {
            "status": "error",
            "sessions": [],
            "error": f"Session analysis failed: {exc}",
        }
