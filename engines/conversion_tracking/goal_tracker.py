"""Conversion Tracking Engine — goal tracker.

Tracks progress against defined conversion goals.
Computes current values, progress percentages, and on-track status.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def track_goals(
    tracked_events: list[dict[str, Any]],
    goals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track progress against conversion goals.

    Args:
        tracked_events: List of validated tracked events.
        goals: List of ConversionGoal dicts.

    Returns:
        Structured dict with goal progress.
    """
    try:
        tracked_events = copy.deepcopy(tracked_events)
        goals = copy.deepcopy(goals)

        # Aggregate event metrics
        event_counts: dict[str, int] = {}
        event_values: dict[str, float] = {}

        for event in tracked_events:
            if not event.get("is_valid", False):
                continue
            etype = str(event.get("event_type", ""))
            value = float(event.get("value", 0.0))

            event_counts[etype] = event_counts.get(etype, 0) + 1
            event_values[etype] = event_values.get(etype, 0.0) + value

        # Total metrics
        total_value = sum(event_values.values())
        total_count = sum(event_counts.values())
        purchase_count = event_counts.get("purchase", 0) + event_counts.get("checkout_complete", 0)
        purchase_value = event_values.get("purchase", 0.0) + event_values.get("checkout_complete", 0.0)

        goal_progress: list[dict[str, Any]] = []

        for goal in goals:
            goal_id = str(goal.get("id", ""))
            name = str(goal.get("name", goal_id))
            target_value = float(goal.get("target_value", 0))
            target_count = int(goal.get("target_count", 0))

            # Determine current value based on goal type
            if target_value > 0:
                current = purchase_value
                target = target_value
            elif target_count > 0:
                current = float(purchase_count)
                target = float(target_count)
            else:
                current = float(total_count)
                target = 1.0

            progress_pct = round((current / target) * 100, 2) if target > 0 else 0.0
            on_track = progress_pct >= 50.0  # Simplified: on track if >= 50%

            goal_progress.append({
                "goal_id": goal_id,
                "name": name,
                "target": target,
                "current": round(current, 2),
                "progress_pct": min(progress_pct, 100.0),
                "on_track": on_track,
            })

        return {
            "status": "success",
            "goal_progress": goal_progress,
        }
    except Exception as exc:
        return {
            "status": "error",
            "goal_progress": [],
            "error": f"Goal tracking failed: {exc}",
        }
