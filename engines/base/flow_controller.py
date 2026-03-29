"""Flow Controller — defines and executes the step sequence within an engine.

Responsibility: Control model execution order. Enforce the standard flow:
  Analyzer (Mistral) → Worker (Qwen) → Creative (LLaMA) → Validator (Mistral)

Stop execution on reject from Analyzer. One step = one model.
"""

from __future__ import annotations

import copy
import time
from typing import Any, Callable

from utils.logger import get_logger
from .engine_types import EngineStep, StepResult, EngineStatus

logger = get_logger("engine.flow_controller")

StepExecutor = Callable[[str, dict[str, Any]], StepResult]


class FlowController:
    """Manages the ordered execution of engine steps."""

    def __init__(self, engine_name: str) -> None:
        self._engine_name = engine_name
        self._steps: list[EngineStep] = []
        self._executors: dict[str, StepExecutor] = {}

    def add_step(self, step: EngineStep) -> None:
        self._steps.append(step)

    def register_executor(self, step_name: str, executor: StepExecutor) -> None:
        self._executors[step_name] = executor

    def get_steps(self) -> list[EngineStep]:
        return list(self._steps)

    def run(self, data: dict[str, Any]) -> list[StepResult]:
        """Execute all steps in sequence. Stop on reject if configured.

        IMPORTANT: Never mutates the original input data — uses deep copy.
        Each step receives accumulated context from prior steps.
        """
        results: list[StepResult] = []
        # Deep copy to prevent input mutation
        working_data = copy.deepcopy(data)

        for step in self._steps:
            executor = self._executors.get(step.name)
            if executor is None:
                if step.required:
                    result = StepResult(
                        step_name=step.name,
                        model_used=step.model_role,
                        status=EngineStatus.FAILED,
                        error=f"No executor registered for required step '{step.name}'",
                    )
                    results.append(result)
                    return results
                continue

            logger.info(
                "[%s] Executing step '%s' (model_role=%s)",
                self._engine_name, step.name, step.model_role,
            )

            start_time = time.monotonic()
            try:
                # Pass a copy so steps can't corrupt working_data
                step_input = copy.deepcopy(working_data)
                result = executor(step.name, step_input)
            except Exception as exc:
                logger.error("[%s] Step '%s' raised: %s", self._engine_name, step.name, exc)
                result = StepResult(
                    step_name=step.name,
                    model_used=step.model_role,
                    status=EngineStatus.FAILED,
                    error=str(exc),
                )
            elapsed = time.monotonic() - start_time

            # Ensure result is always a StepResult (defensive)
            if not isinstance(result, StepResult):
                logger.error("[%s] Step '%s' returned non-StepResult: %s", self._engine_name, step.name, type(result))
                result = StepResult(
                    step_name=step.name,
                    model_used=step.model_role,
                    status=EngineStatus.FAILED,
                    error=f"Step returned {type(result).__name__} instead of StepResult",
                )

            results.append(result)
            logger.info("[%s] Step '%s' completed in %.3fs (status=%s)",
                        self._engine_name, step.name, elapsed, result.status.value)

            # Stop on reject
            if result.status == EngineStatus.REJECTED and step.stop_on_reject:
                logger.info("[%s] Step '%s' rejected — stopping flow", self._engine_name, step.name)
                return results

            # Stop on failure for required steps
            if result.status == EngineStatus.FAILED and step.required:
                logger.error("[%s] Required step '%s' failed — stopping flow", self._engine_name, step.name)
                return results

            # Pass step output forward as input for next step
            if result.output and isinstance(result.output, dict):
                working_data.update(result.output)

        return results
