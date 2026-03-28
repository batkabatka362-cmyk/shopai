"""Task Executor — executes individual tasks."""
from __future__ import annotations
from typing import Any, Callable
from utils.helpers import generate_id, timestamp_now
from utils.logger import get_logger

logger = get_logger("exec.task_executor")


class TaskExecutor:
    def execute(self, task: dict[str, Any], handler: Callable | None = None) -> dict[str, Any]:
        task_id = task.get("id", generate_id("exec"))
        logger.info("Executing task %s", task_id)
        if handler:
            try:
                result = handler(task)
                return {"task_id": task_id, "status": "completed", "result": result, "timestamp": timestamp_now()}
            except Exception as e:
                return {"task_id": task_id, "status": "failed", "error": str(e), "timestamp": timestamp_now()}
        return {"task_id": task_id, "status": "completed", "result": task, "timestamp": timestamp_now()}
