"""Time Intelligence — status tracker.

Tracks execution status of all tasks through their lifecycle:
pending -> queued -> triggered -> running -> completed | failed | retrying.

Model note: Would use Qwen for structured status aggregation.
"""
from __future__ import annotations

import copy
import time
from typing import Any


_VALID_STATUSES = frozenset({
    "pending", "queued", "triggered", "running",
    "completed", "failed", "retrying", "blocked", "delayed",
})


class StatusTracker:
    """Maintains the execution status of every task."""

    def __init__(self) -> None:
        self._statuses: dict[str, dict[str, Any]] = {}

    def initialize(self, task_id: str, status: str = "pending") -> None:
        """Initialize tracking for a task."""
        self._statuses[task_id] = {
            "task_id": task_id,
            "status": status if status in _VALID_STATUSES else "pending",
            "started_at": None,
            "completed_at": None,
            "error": None,
            "attempt": 0,
        }

    def update(self, task_id: str, status: str, error: str | None = None) -> None:
        """Update the status of a task."""
        if task_id not in self._statuses:
            self.initialize(task_id)

        entry = self._statuses[task_id]
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if status in _VALID_STATUSES:
            entry["status"] = status

        if status == "running" and entry["started_at"] is None:
            entry["started_at"] = timestamp

        if status in ("completed", "failed"):
            entry["completed_at"] = timestamp

        if status == "failed":
            entry["error"] = error
            entry["attempt"] = entry.get("attempt", 0) + 1

        if status == "retrying":
            entry["attempt"] = entry.get("attempt", 0) + 1
            entry["error"] = error

    def get(self, task_id: str) -> dict[str, Any]:
        """Get the current status of a task."""
        return copy.deepcopy(self._statuses.get(task_id, {
            "task_id": task_id,
            "status": "unknown",
            "started_at": None,
            "completed_at": None,
            "error": None,
            "attempt": 0,
        }))

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Get all tracked statuses."""
        return copy.deepcopy(self._statuses)

    def get_by_status(self, status: str) -> list[dict[str, Any]]:
        """Get all tasks with a given status."""
        return [
            copy.deepcopy(v)
            for v in self._statuses.values()
            if v.get("status") == status
        ]


def build_initial_statuses(
    classified_tasks: list[dict[str, Any]],
    blocked_task_ids: set[str],
    queue_entry_ids: set[str],
    triggered_ids: set[str],
) -> dict[str, Any]:
    """Build initial status entries for all tasks.

    Args:
        classified_tasks: All classified tasks.
        blocked_task_ids: Tasks that are blocked.
        queue_entry_ids: Tasks that are in the queue.
        triggered_ids: Tasks that have been triggered.

    Returns:
        Structured dict with status entries and a StatusTracker instance.
    """
    try:
        tracker = StatusTracker()
        statuses: list[dict[str, Any]] = []

        for task in classified_tasks:
            task_id = task["task_id"]

            if task_id in triggered_ids:
                status = "triggered"
            elif task_id in blocked_task_ids:
                status = "blocked"
            elif task_id in queue_entry_ids:
                status = "queued"
            else:
                status = "pending"

            tracker.initialize(task_id, status)
            statuses.append(tracker.get(task_id))

        return {
            "status": "success",
            "task_statuses": statuses,
            "tracker": tracker,
            "counts": {
                "triggered": len(triggered_ids),
                "blocked": len(blocked_task_ids),
                "queued": len(queue_entry_ids - triggered_ids - blocked_task_ids),
                "pending": len(classified_tasks) - len(queue_entry_ids) - len(blocked_task_ids),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "task_statuses": [],
            "tracker": StatusTracker(),
            "counts": {},
            "error": str(exc),
        }
