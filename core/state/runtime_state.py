from __future__ import annotations

import threading
from typing import Any

from utils.helpers import timestamp_now
from utils.logger import get_logger

logger = get_logger("state.runtime")

_TERMINAL_STATUSES = frozenset({"completed", "failed"})


class RuntimeState:
    """Tracks ephemeral runtime state for active task execution."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._metrics: dict[str, Any] = {
            "tasks_started": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
        }
        # Lock guarding _tasks + _metrics. Concurrent task
        # registration / updates from multiple cycles previously
        # raced on dict mutations and `+= 1` on the metric
        # counters.
        self._lock = threading.Lock()

    def register_task(self, task_id: str, task_type: str) -> None:
        with self._lock:
            self._tasks[task_id] = {
                "type": task_type,
                "status": "pending",
                "started_at": timestamp_now(),
                "result": None,
                "error": None,
            }
            self._metrics["tasks_started"] += 1
        logger.info("Task %s registered (type=%s)", task_id, task_type)

    def update_task(self, task_id: str, status: str, result: Any = None, error: str | None = None) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                logger.warning("Task %s not found in runtime state", task_id)
                return
            previous_status = task.get("status")
            task["status"] = status
            task["result"] = result
            task["error"] = error
            # Only count the FIRST transition into a terminal state
            # so re-updating an already-completed task doesn't
            # double-bump the metrics. Without this guard, an
            # idempotent retry that re-marks "completed" inflated
            # tasks_completed indefinitely.
            if status in _TERMINAL_STATUSES and previous_status not in _TERMINAL_STATUSES:
                if status == "completed":
                    self._metrics["tasks_completed"] += 1
                elif status == "failed":
                    self._metrics["tasks_failed"] += 1

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            # Return a defensive copy so caller mutation can't
            # corrupt internal state.
            return dict(task) if task is not None else None

    def get_active_tasks(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                tid: dict(t) for tid, t in self._tasks.items()
                if t.get("status") in ("pending", "running")
            }

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._metrics)

    def clear_completed(self) -> int:
        with self._lock:
            completed = [
                tid for tid, t in self._tasks.items()
                if t.get("status") in _TERMINAL_STATUSES
            ]
            for tid in completed:
                del self._tasks[tid]
            return len(completed)
