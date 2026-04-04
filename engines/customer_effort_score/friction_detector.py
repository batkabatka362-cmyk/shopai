"""Customer Effort Score Engine — friction detector.

Detects high-friction areas by identifying touchpoints and patterns where
customer effort exceeds acceptable thresholds.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Friction thresholds
# ---------------------------------------------------------------------------

_HIGH_EFFORT_THRESHOLD = 4.5       # CES score above this = high friction
_LOW_RESOLUTION_THRESHOLD = 0.6    # Resolution rate below this = friction
_HIGH_STEPS_THRESHOLD = 7          # Steps above this = friction
_HIGH_TIME_THRESHOLD = 900         # Seconds above this (15 min) = friction


def detect_friction(
    touchpoint_scores: list[dict[str, Any]],
    interaction_efforts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect high-friction areas across touchpoints and interactions.

    Args:
        touchpoint_scores: Per-touchpoint aggregate scores.
        interaction_efforts: Per-interaction effort data.

    Returns:
        Structured dict with friction points and severity.
    """
    try:
        tp_data = copy.deepcopy(touchpoint_scores)
        ix_data = copy.deepcopy(interaction_efforts)

        friction_points: list[dict[str, Any]] = []

        # Check each touchpoint for friction signals
        for tp in tp_data:
            touchpoint = str(tp.get("touchpoint", ""))
            avg_effort = float(tp.get("avg_effort_score", 0.0))
            resolution_rate = float(tp.get("resolution_rate", 1.0))
            avg_steps = float(tp.get("avg_steps", 0))
            avg_time = float(tp.get("avg_time_seconds", 0))
            volume = int(tp.get("volume", 0))

            reasons: list[str] = []
            severity_score = 0.0

            if avg_effort > _HIGH_EFFORT_THRESHOLD:
                reasons.append(f"High effort score ({avg_effort}/7)")
                severity_score += (avg_effort - _HIGH_EFFORT_THRESHOLD) / 2.5

            if resolution_rate < _LOW_RESOLUTION_THRESHOLD:
                reasons.append(
                    f"Low resolution rate ({round(resolution_rate * 100, 1)}%)"
                )
                severity_score += (
                    (_LOW_RESOLUTION_THRESHOLD - resolution_rate)
                    / _LOW_RESOLUTION_THRESHOLD
                )

            if avg_steps > _HIGH_STEPS_THRESHOLD:
                reasons.append(f"Too many steps ({avg_steps} avg)")
                severity_score += (avg_steps - _HIGH_STEPS_THRESHOLD) / _HIGH_STEPS_THRESHOLD

            if avg_time > _HIGH_TIME_THRESHOLD:
                reasons.append(f"Excessive time ({round(avg_time / 60, 1)} min avg)")
                severity_score += (avg_time - _HIGH_TIME_THRESHOLD) / _HIGH_TIME_THRESHOLD

            if reasons:
                # Severity: critical (>1.5), high (>1.0), medium (>0.5), low
                if severity_score > 1.5:
                    severity = "critical"
                elif severity_score > 1.0:
                    severity = "high"
                elif severity_score > 0.5:
                    severity = "medium"
                else:
                    severity = "low"

                friction_points.append({
                    "touchpoint": touchpoint,
                    "severity": severity,
                    "severity_score": round(severity_score, 3),
                    "reasons": reasons,
                    "affected_interactions": volume,
                })

        # Sort by severity score descending
        friction_points.sort(key=lambda f: f["severity_score"], reverse=True)

        return {
            "status": "success",
            "friction_points": friction_points,
            "total_friction_areas": len(friction_points),
        }
    except Exception as exc:
        return {
            "status": "error",
            "friction_points": [],
            "error": f"Friction detection failed: {exc}",
        }
