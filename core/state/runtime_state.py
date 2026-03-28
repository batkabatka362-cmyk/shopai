from __future__ import annotations

from typing import Any

from utils.helpers import timestamp_now
from utils.logger import get_logger

logger = get_logger("state.runtime")


class RuntimeState:
    """Tracks ephemeral runtime state for active task execution."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._metrics: dict[str, Any] = {
            "tasks_started": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
        }

    def register_task(self, task_id: str, task_type: str) -> None:
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
        if task_id not in self._tasks:
            logger.warning("Task %s not found in runtime state", task_id)
            return
        self._tasks[task_id]["status"] = status
        self._tasks[task_id]["result"] = result
        self._tasks[task_id]["error"] = error
        if status == "completed":
            self._metrics["tasks_completed"] += 1
        elif status == "failed":
            self._metrics["tasks_failed"] += 1

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._tasks.get(task_id)

    def get_active_tasks(self) -> dict[str, dict[str, Any]]:
        return {
            tid: t for tid, t in self._tasks.items()
            if t["status"] in ("pending", "running")
        }

    def get_metrics(self) -> dict[str, Any]:
        return dict(self._metrics)

    def clear_completed(self) -> int:
        completed = [
            tid for tid, t in self._tasks.items()
            if t["status"] in ("completed", "failed")
        ]
        for tid in completed:
            del self._tasks[tid]
        return len(completed)
