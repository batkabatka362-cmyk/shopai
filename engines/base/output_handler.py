"""Output Handler — formats and returns structured engine results.

Responsibility: Ensure all engine output is consistent, structured, and reusable.
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from .engine_types import EngineOutput, EngineStatus, StepResult

logger = get_logger("engine.output_handler")


class OutputHandler:
    """Constructs the final EngineOutput from step results."""

    def __init__(self, engine_name: str) -> None:
        self._engine_name = engine_name

    def build_output(
        self,
        task_id: str,
        steps: list[StepResult],
        final_result: dict[str, Any] | None = None,
    ) -> EngineOutput:
        status = self._derive_status(steps)
        error = self._collect_errors(steps) if status == EngineStatus.FAILED else None

        output = EngineOutput(
            task_id=task_id,
            engine_name=self._engine_name,
            status=status,
            result=final_result or self._merge_step_outputs(steps),
            steps=steps,
            error=error,
        )

        logger.info("[%s] Output built: status=%s", self._engine_name, status.value)
        return output

    @staticmethod
    def _derive_status(steps: list[StepResult]) -> EngineStatus:
        if not steps:
            return EngineStatus.FAILED

        last = steps[-1]
        if last.status == EngineStatus.REJECTED:
            return EngineStatus.REJECTED

        if any(s.status == EngineStatus.FAILED for s in steps):
            return EngineStatus.FAILED

        return EngineStatus.COMPLETED

    @staticmethod
    def _collect_errors(steps: list[StepResult]) -> str:
        errors = [
            f"{s.step_name}: {s.error}"
            for s in steps
            if s.error
        ]
        return "; ".join(errors)

    @staticmethod
    def _merge_step_outputs(steps: list[StepResult]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for step in steps:
            if step.output and step.status != EngineStatus.FAILED:
                merged[step.step_name] = step.output
        return merged
