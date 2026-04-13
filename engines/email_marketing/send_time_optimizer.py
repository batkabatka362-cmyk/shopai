"""Email Marketing Engine — send time optimizer.

Determines the optimal send time: best day of week, hour of day,
timezone handling, and frequency capping.  Uses engagement data
heuristics — no model needed.

Model note: no model usage — deterministic optimization.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# ---------------------------------------------------------------------------
# Engagement heatmap: day-of-week x hour-of-day → expected open rate
# Based on aggregated email marketing benchmarks.
# Hours are in UTC (0-23).
# ---------------------------------------------------------------------------

_DAY_SCORES: dict[str, float] = {
    "Tuesday": 0.92,
    "Wednesday": 0.88,
    "Thursday": 0.86,
    "Monday": 0.80,
    "Friday": 0.72,
    "Saturday": 0.55,
    "Sunday": 0.50,
}

_HOUR_SCORES: dict[int, float] = {
    10: 0.95,   # 10 AM — peak open time
    11: 0.90,
    9: 0.88,
    14: 0.85,   # 2 PM — post-lunch check
    13: 0.80,
    8: 0.75,
    15: 0.72,
    12: 0.70,
    16: 0.65,
    7: 0.60,
    17: 0.55,
    18: 0.50,
    19: 0.45,
    20: 0.42,
    6: 0.38,
    21: 0.35,
    22: 0.30,
    23: 0.25,
    0: 0.20,
    1: 0.15,
    2: 0.12,
    3: 0.10,
    4: 0.10,
    5: 0.15,
}

# Goal-specific adjustments
_GOAL_DAY_OVERRIDES: dict[str, str] = {
    "promotional": "Tuesday",
    "nurture": "Wednesday",
    "win-back": "Thursday",
    "announcement": "Monday",
}

_GOAL_HOUR_OVERRIDES: dict[str, int] = {
    "promotional": 10,
    "nurture": 9,
    "win-back": 14,
    "announcement": 11,
}

# Frequency caps per campaign type (minimum hours between sends)
_FREQUENCY_CAPS: dict[str, int] = {
    "promotional": 48,
    "nurture": 72,
    "win-back": 120,
    "announcement": 24,
}


def optimize_send_time(
    goal: str,
    audience_segments: list[str],
) -> dict[str, Any]:
    """Determine optimal send time for the campaign.

    Args:
        goal: Campaign goal / type.
        audience_segments: Selected audience segments.

    Returns:
        Structured dict with SendTimeRecommendation data.
    """
    try:
        goal_key = str(goal).lower().strip()
        segments = copy.deepcopy(audience_segments)

        # Pick best day for this goal
        recommended_day = _GOAL_DAY_OVERRIDES.get(goal_key, "Tuesday")
        day_score = _DAY_SCORES.get(recommended_day, 0.80)

        # Pick best hour for this goal
        recommended_hour = _GOAL_HOUR_OVERRIDES.get(goal_key, 10)
        hour_score = _HOUR_SCORES.get(recommended_hour, 0.80)

        # Segment-based adjustments
        # VIP customers tend to open earlier; lapsed open later
        if "vip" in segments:
            recommended_hour = max(recommended_hour - 1, 7)
        if "lapsed" in segments or "dormant" in segments:
            recommended_hour = min(recommended_hour + 2, 18)

        # Build timezone and ISO time
        timezone = "UTC"
        now = time.gmtime()
        # Find the next occurrence of recommended_day
        day_index = _day_name_to_index(recommended_day)
        days_ahead = (day_index - now.tm_wday) % 7
        if days_ahead == 0 and now.tm_hour >= recommended_hour:
            days_ahead = 7  # skip to next week

        send_timestamp = time.mktime(time.struct_time((
            now.tm_year, now.tm_mon, now.tm_mday + days_ahead,
            recommended_hour, 0, 0,
            day_index, 0, -1,
        )))
        iso_send_time = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(send_timestamp),
        )

        # Frequency cap
        cap_hours = _FREQUENCY_CAPS.get(goal_key, 48)
        frequency_cap = f"No more than 1 send per {cap_hours} hours for this segment"

        # Rationale
        combined_score = round(day_score * 0.5 + hour_score * 0.5, 2)
        rationale = (
            f"{recommended_day} at {recommended_hour}:00 {timezone} scores "
            f"{combined_score:.2f} (day={day_score:.2f}, hour={hour_score:.2f}). "
            f"Optimized for '{goal_key}' campaigns targeting {', '.join(segments)}."
        )

        return {
            "status": "success",
            "send_time": {
                "recommended_day": recommended_day,
                "recommended_hour": recommended_hour,
                "timezone": timezone,
                "iso_send_time": iso_send_time,
                "frequency_cap": frequency_cap,
                "rationale": rationale,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "send_time": {},
            "error": f"Send time optimization failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _day_name_to_index(day_name: str) -> int:
    """Convert day name to Python weekday index (Monday=0)."""
    mapping = {
        "Monday": 0,
        "Tuesday": 1,
        "Wednesday": 2,
        "Thursday": 3,
        "Friday": 4,
        "Saturday": 5,
        "Sunday": 6,
    }
    return mapping.get(day_name, 1)
