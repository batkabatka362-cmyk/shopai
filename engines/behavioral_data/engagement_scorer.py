"""Behavioral Data Engine — engagement scorer.

Scores user engagement based on session depth, frequency,
recency, and interaction quality. Outputs tiered scores.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Engagement tier thresholds
# ---------------------------------------------------------------------------

_HIGH_THRESHOLD = 0.7
_MEDIUM_THRESHOLD = 0.4


def score_engagement(
    sessions: list[dict[str, Any]],
    click_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score engagement for each user/session.

    Args:
        sessions: Analyzed session patterns.
        click_summaries: Click tracking summaries.

    Returns:
        Structured dict with engagement scores.
    """
    try:
        session_data = copy.deepcopy(sessions)

        # Build CTR map for products
        ctr_map: dict[str, float] = {}
        for cs in click_summaries:
            pid = cs.get("product_id", "")
            ctr_map[pid] = cs.get("click_through_rate", 0.0)

        avg_ctr = (
            sum(ctr_map.values()) / len(ctr_map) if ctr_map else 0.0
        )

        scores: list[dict[str, Any]] = []

        for session in session_data:
            sid = str(session.get("session_id", "unknown"))
            duration = float(session.get("duration_seconds", 0))
            pages = int(session.get("pages_viewed", 0))
            converted = bool(session.get("conversion", False))
            bounced = bool(session.get("bounce", False))

            # Factor scores (0.0 to 1.0)
            depth_score = min(pages / 10.0, 1.0) if pages > 0 else 0.0
            duration_score = min(duration / 300.0, 1.0) if duration > 0 else 0.0
            conversion_score = 1.0 if converted else 0.0
            bounce_penalty = 0.0 if bounced else 0.3

            factors = {
                "depth": round(depth_score, 3),
                "duration": round(duration_score, 3),
                "conversion": conversion_score,
                "no_bounce_bonus": bounce_penalty,
            }

            overall = round(
                depth_score * 0.25 +
                duration_score * 0.25 +
                conversion_score * 0.3 +
                bounce_penalty * 0.2,
                3,
            )

            if overall >= _HIGH_THRESHOLD:
                level = "high"
            elif overall >= _MEDIUM_THRESHOLD:
                level = "medium"
            else:
                level = "low"

            scores.append({
                "entity_id": sid,
                "score": overall,
                "level": level,
                "factors": factors,
            })

        return {
            "status": "success",
            "scores": scores,
            "total_scored": len(scores),
        }
    except Exception as exc:
        return {
            "status": "error",
            "scores": [],
            "error": f"Engagement scoring failed: {exc}",
        }
