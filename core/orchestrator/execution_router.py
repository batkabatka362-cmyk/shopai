from __future__ import annotations

from typing import Any, Callable

from utils.helpers import generate_id, timestamp_now
from utils.logger import get_logger

logger = get_logger("orchestrator.execution_router")


class ExecutionRouter:
    """Routes resolved tasks to execution handlers and manages their lifecycle."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._execution_log: list[dict[str, Any]] = []

    def register_handler(self, engine_name: str, handler: Callable[..., Any]) -> None:
        self._handlers[engine_name] = handler
        logger.info("Registered execution handler for engine=%s", engine_name)

    def execute(self, engine_name: str, task_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        handler = self._handlers.get(engine_name)
        if handler is None:
            error_msg = f"No handler registered for engine={engine_name}"
            logger.error(error_msg)
            return self._make_result(task_id, engine_name, "failed", error=error_msg)

        logger.info("Executing task %s on engine=%s", task_id, engine_name)
        try:
            result = handler(task_id=task_id, params=params or {})
            record = self._make_result(task_id, engine_name, "completed", result=result)
        except Exception as exc:
            logger.error("Task %s failed: %s", task_id, exc)
            record = self._make_result(task_id, engine_name, "failed", error=str(exc))

        self._execution_log.append(record)
        return record

    def has_handler(self, engine_name: str) -> bool:
        return engine_name in self._handlers

    def list_handlers(self) -> list[str]:
        return list(self._handlers.keys())

    def get_execution_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._execution_log[-limit:]

    @staticmethod
    def _make_result(
        task_id: str,
        engine: str,
        status: str,
        result: Any = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "task_id": task_id,
            "engine": engine,
            "status": status,
            "result": result,
            "error": error,
            "timestamp": timestamp_now(),
        }
