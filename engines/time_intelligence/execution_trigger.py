"""Time Intelligence — execution trigger.

Triggers execution for tasks that are ready, after verifying all
preconditions: dependencies resolved, not blocked, within schedule window,
and present in the queue.

Tasks are NOT executed directly here — this module only produces trigger
decisions that downstream systems act upon.

Model note: Would use LLaMA for complex timing strategy decisions.
"""
from __future__ import annotations

import copy
import time
from datetime import datetime, timezone
from typing import Any


_SCHEDULE_WINDOW_TOLERANCE_SECONDS = 300.0


def trigger_ready_tasks(
    queue_entries: list[dict[str, Any]],
    ready_task_ids: list[str],
    blocked_task_ids: set[str],
    execution_statuses: dict[str, dict[str, Any]],
    current_time: str,
) -> dict[str, Any]:
    """Determine which queued tasks should be triggered for execution.

    Args:
        queue_entries: Current queue entries.
        ready_task_ids: Task IDs whose dependencies are satisfied.
        blocked_task_ids: Task IDs that are blocked.
        execution_statuses: Current status per task from the status tracker.
        current_time: ISO timestamp of current time.

    Returns:
        Structured dict with triggered task IDs and skipped tasks with reasons.
    """
    try:
        queue_entries = copy.deepcopy(queue_entries)
        current_dt = _parse_time(current_time)
        ready_set = set(ready_task_ids)

        triggered: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for entry in queue_entries:
            task_id = entry.get("task_id", "")

            if task_id in blocked_task_ids:
                skipped.append({
                    "task_id": task_id,
                    "reason": "blocked_dependency",
                })
                continue

            status_info = execution_statuses.get(task_id, {})
            current_status = status_info.get("status", "pending")
            if current_status in ("running", "completed"):
                skipped.append({
                    "task_id": task_id,
                    "reason": f"already_{current_status}",
                })
                continue

            if current_status == "failed":
                attempt = status_info.get("attempt", 0)
                if attempt >= 3:
                    skipped.append({
                        "task_id": task_id,
                        "reason": "max_retries_exceeded",
                    })
                    continue

            if task_id not in ready_set:
                skipped.append({
                    "task_id": task_id,
                    "reason": "dependencies_not_met",
                })
                continue

            scheduled_time_str = entry.get("scheduled_time", "")
            if scheduled_time_str:
                passes, reason = _check_schedule_window(
                    scheduled_time_str, current_dt,
                )
                if not passes:
                    skipped.append({
                        "task_id": task_id,
                        "reason": reason,
                    })
                    continue

            triggered.append({
                "task_id": task_id,
                "trigger_time": current_time,
                "priority_score": entry.get("priority_score", 0.0),
                "status": "triggered",
            })

        triggered.sort(key=lambda t: t.get("priority_score", 0.0), reverse=True)

        return {
            "status": "success",
            "triggered": triggered,
            "skipped": skipped,
            "triggered_count": len(triggered),
            "skipped_count": len(skipped),
        }
    except Exception as exc:
        return {
            "status": "error",
            "triggered": [],
            "skipped": [],
            "triggered_count": 0,
            "skipped_count": 0,
            "error": str(exc),
        }


def _check_schedule_window(
    scheduled_time_str: str,
    current_dt: datetime,
) -> tuple[bool, str]:
    """Check if the current time falls within the acceptable schedule window."""
    try:
        scheduled_dt = _parse_time(scheduled_time_str)
        diff_seconds = (current_dt - scheduled_dt).total_seconds()

        if diff_seconds < -_SCHEDULE_WINDOW_TOLERANCE_SECONDS:
            return False, "too_early"

        return True, "within_window"
    except (ValueError, TypeError):
        return True, "unparseable_schedule_time"


def _parse_time(time_str: str) -> datetime:
    """Parse an ISO time string into a timezone-aware datetime."""
    return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
