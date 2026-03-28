"""Workflow Runner — executes automated workflows."""
from __future__ import annotations
from typing import Any, Callable
from utils.logger import get_logger

logger = get_logger("exec.workflow_runner")


class WorkflowRunner:
    def __init__(self) -> None:
        self._workflows: dict[str, list[Callable]] = {}

    def register(self, name: str, steps: list[Callable]) -> None:
        self._workflows[name] = steps

    def run(self, name: str, initial_data: dict[str, Any]) -> dict[str, Any]:
        steps = self._workflows.get(name, [])
        if not steps:
            return {"status": "error", "error": f"Workflow '{name}' not found"}
        data = initial_data
        for i, step in enumerate(steps):
            data = step(data)
            logger.info("[%s] Step %d complete", name, i + 1)
        return {"status": "completed", "result": data}
