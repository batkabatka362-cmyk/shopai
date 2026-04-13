"""Behavioral Data Engine — session analyzer.

Analyzes session patterns: duration, page depth, bounce rate,
conversion events, and session quality classification.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Session classification thresholds
# ---------------------------------------------------------------------------

_BOUNCE_MAX_PAGES = 1
_SHORT_SESSION_SECONDS = 10
_LONG_SESSION_SECONDS = 600


def analyze_sessions(
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze session patterns across all sessions.

    Args:
        sessions: List of session records.

    Returns:
        Structured dict with session patterns and aggregate stats.
    """
    try:
        data = copy.deepcopy(sessions)
        patterns: list[dict[str, Any]] = []

        total_duration = 0.0
        bounce_count = 0
        conversion_count = 0

        for session in data:
            session_id = str(session.get("session_id", session.get("id", "unknown")))
            duration = float(session.get("duration_seconds", session.get("duration", 0)))
            pages = int(session.get("pages_viewed", session.get("page_count", 0)))
            converted = bool(session.get("converted", session.get("conversion", False)))

            is_bounce = pages <= _BOUNCE_MAX_PAGES and duration < _SHORT_SESSION_SECONDS

            total_duration += duration
            if is_bounce:
                bounce_count += 1
            if converted:
                conversion_count += 1

            patterns.append({
                "session_id": session_id,
                "duration_seconds": round(duration, 1),
                "pages_viewed": pages,
                "bounce": is_bounce,
                "conversion": converted,
            })

        total = len(patterns) or 1
        avg_duration = round(total_duration / total, 1)
        bounce_rate = round(bounce_count / total * 100, 1)
        conversion_rate = round(conversion_count / total * 100, 1)

        return {
            "status": "success",
            "patterns": patterns,
            "aggregate": {
                "total_sessions": len(patterns),
                "avg_duration_seconds": avg_duration,
                "bounce_rate_pct": bounce_rate,
                "conversion_rate_pct": conversion_rate,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "patterns": [],
            "error": f"Session analysis failed: {exc}",
        }
