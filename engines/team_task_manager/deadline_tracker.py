"""Team Task Manager Engine — deadline tracker.

Tracks deadlines and SLAs for tasks. Computes time remaining,
identifies overdue tasks, and flags upcoming deadlines.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# ---------------------------------------------------------------------------
# SLA defaults (hours)
# ---------------------------------------------------------------------------

_SLA_HOURS: dict[str, int] = {
    "P0": 4,     # 4 hours
    "P1": 24,    # 1 day
    "P2": 72,    # 3 days
    "P3": 168,   # 7 days
}

_URGENT_THRESHOLD_HOURS = 2  # tasks due within 2 hours = urgent


def track_deadlines(
    tasks: list[dict[str, Any]],
    current_timestamp: float | None = None,
) -> dict[str, Any]:
    """Track deadlines and SLA compliance for all tasks.

    Assigns deadlines based on priority level, computes time remaining,
    and flags overdue or soon-due tasks.

    Args:
        tasks: Priority-ranked tasks from priority_ranker.
        current_timestamp: Current unix timestamp (defaults to now).

    Returns:
        Structured dict with deadline-tracked tasks and overdue count.
    """
    try:
        items = copy.deepcopy(tasks)
        now = current_timestamp or time.time()

        tracked: list[dict[str, Any]] = []
        overdue_count = 0
        urgent_count = 0

        for task in items:
            priority = str(task.get("priority", "P2"))
            created_at = float(task.get("created_at", now))

            sla_hours = _SLA_HOURS.get(priority, 72)
            deadline_ts = created_at + (sla_hours * 3600)
            hours_remaining = round((deadline_ts - now) / 3600, 1)

            if hours_remaining < 0:
                deadline_status = "overdue"
                overdue_count += 1
            elif hours_remaining <= _URGENT_THRESHOLD_HOURS:
                deadline_status = "urgent"
                urgent_count += 1
            elif hours_remaining <= sla_hours * 0.5:
                deadline_status = "approaching"
            else:
                deadline_status = "on_track"

            task["deadline"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(deadline_ts),
            )
            task["sla_hours"] = sla_hours
            task["hours_remaining"] = hours_remaining
            task["deadline_status"] = deadline_status

            tracked.append(task)

        # Sort: overdue first, then urgent, then by hours remaining
        status_order = {"overdue": 0, "urgent": 1, "approaching": 2, "on_track": 3}
        tracked.sort(
            key=lambda t: (
                status_order.get(t.get("deadline_status", "on_track"), 4),
                t.get("hours_remaining", 999),
            ),
        )

        return {
            "status": "success",
            "tracked_tasks": tracked,
            "overdue_count": overdue_count,
            "urgent_count": urgent_count,
        }
    except Exception as exc:
        return {
            "status": "error",
            "tracked_tasks": [],
            "overdue_count": 0,
            "error": f"Deadline tracking failed: {exc}",
        }
