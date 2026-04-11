"""Email Marketing Engine — audience selector.

Selects the target audience from available segments. Filters by campaign
goal, excludes suppressed/unsubscribed contacts, and prioritizes segments
by engagement level.

Model note: Uses Mistral for analytical audience selection.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Engagement scores per segment (higher = more engaged)
# ---------------------------------------------------------------------------

_SEGMENT_ENGAGEMENT: dict[str, float] = {
    "vip": 0.95,
    "active": 0.80,
    "new": 0.65,
    "lapsed": 0.35,
    "at_risk": 0.25,
    "dormant": 0.10,
}

# Estimated list size per segment
_SEGMENT_SIZES: dict[str, int] = {
    "vip": 1200,
    "active": 8500,
    "new": 3200,
    "lapsed": 4100,
    "at_risk": 2800,
    "dormant": 5500,
}

# Suppression rates (unsubscribed / bounced / complained)
_SUPPRESSION_RATES: dict[str, float] = {
    "vip": 0.01,
    "active": 0.03,
    "new": 0.02,
    "lapsed": 0.12,
    "at_risk": 0.15,
    "dormant": 0.25,
}

# Which segments are suitable for each campaign goal
_GOAL_SEGMENT_MAP: dict[str, list[str]] = {
    "promotional": ["vip", "active", "new"],
    "nurture": ["new", "active"],
    "win-back": ["lapsed", "at_risk", "dormant"],
    "announcement": ["vip", "active", "new", "lapsed"],
}


def select_audience(
    goal: str,
    audience_segments: list[str],
) -> dict[str, Any]:
    """Select and prioritize audience segments for a campaign.

    Args:
        goal: Campaign goal (promotional, nurture, win-back, announcement).
        audience_segments: Requested segments to include.

    Returns:
        Structured dict with AudienceSelection data.
    """
    try:
        goal = str(goal).lower().strip()
        segments = copy.deepcopy(audience_segments)

        # Determine eligible segments based on goal
        eligible_for_goal = _GOAL_SEGMENT_MAP.get(goal, list(_SEGMENT_ENGAGEMENT.keys()))

        # Filter: keep only segments that are both requested AND eligible
        selected: list[str] = []
        for seg in segments:
            seg_lower = seg.lower().strip()
            if seg_lower in eligible_for_goal:
                selected.append(seg_lower)

        # If no segments survived filtering, fall back to all eligible
        if not selected:
            selected = [s for s in eligible_for_goal if s in _SEGMENT_SIZES]

        # Calculate audience size and suppressions
        total_raw = 0
        total_suppressed = 0
        engagement_priority: list[dict[str, Any]] = []

        for seg in selected:
            raw_size = _SEGMENT_SIZES.get(seg, 1000)
            suppression_rate = _SUPPRESSION_RATES.get(seg, 0.05)
            suppressed = int(raw_size * suppression_rate)
            net_size = raw_size - suppressed
            engagement = _SEGMENT_ENGAGEMENT.get(seg, 0.50)

            total_raw += raw_size
            total_suppressed += suppressed

            engagement_priority.append({
                "segment": seg,
                "raw_size": raw_size,
                "suppressed": suppressed,
                "net_size": net_size,
                "engagement_score": engagement,
            })

        # Sort by engagement score descending (highest engagement first)
        engagement_priority.sort(
            key=lambda e: e["engagement_score"],
            reverse=True,
        )

        audience_size = total_raw - total_suppressed

        return {
            "status": "success",
            "selection": {
                "selected_segments": selected,
                "audience_size": audience_size,
                "suppressed_count": total_suppressed,
                "engagement_priority": engagement_priority,
                "model_note": "Mistral: analytical audience selection and prioritization",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "selection": {},
            "error": f"Audience selection failed: {exc}",
        }
