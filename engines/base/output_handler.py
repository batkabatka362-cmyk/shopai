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
        """Merge step outputs into a flat result dict.

        Strategy: later steps override earlier ones for same keys.
        Also keeps step-namespaced copy for full traceability.
        Final result has both flat fields and _steps namespace.
        """
        merged: dict[str, Any] = {}
        steps_detail: dict[str, Any] = {}

        for step in steps:
            if step.output and step.status != EngineStatus.FAILED:
                steps_detail[step.step_name] = step.output
                # Flatten important fields to top level
                for key, value in step.output.items():
                    if key.startswith("_"):
                        continue  # Skip internal fields
                    if key in ("request_id", "model", "role", "raw_prompt", "context_keys"):
                        continue  # Skip model metadata
                    merged[key] = value

        merged["_steps"] = steps_detail
        return merged
