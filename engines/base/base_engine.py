"""BaseEngine — abstract base class that all engines must extend.

Enforces the Engine Build Standard:
  InputHandler → FlowController → Models → Validator → OutputHandler

Every engine inherits this class and implements:
  - define_steps(): register the engine's execution steps
  - Each step executor method
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from utils.logger import get_logger
from .engine_types import EngineInput, EngineOutput, EngineStatus
from .input_handler import InputHandler
from .flow_controller import FlowController
from .validator import OutputValidator
from .output_handler import OutputHandler


# Global learning hook — set by orchestrator, never modifies code
_feedback_store = None


def set_feedback_store(store) -> None:
    """Set the global feedback store for all engines. Called once at startup."""
    global _feedback_store
    _feedback_store = store


class BaseEngine(ABC):
    """Abstract base for all ShopAI engines.

    Subclasses must:
      1. Set engine_name and required_input_fields / required_output_fields
      2. Implement define_steps() to register steps and executors
    """

    engine_name: str = "base"
    required_input_fields: list[str] = []
    required_output_fields: list[str] = []

    def __init__(self) -> None:
        self.logger = get_logger(f"engine.{self.engine_name}")
        self.input_handler = InputHandler(self.engine_name, self.required_input_fields)
        self.flow = FlowController(self.engine_name)
        self.validator = OutputValidator(self.engine_name, self.required_output_fields)
        self.output_handler = OutputHandler(self.engine_name)
        self.define_steps()

    @abstractmethod
    def define_steps(self) -> None:
        """Register EngineSteps and their executor callables on self.flow."""

    def run(self, engine_input: EngineInput) -> EngineOutput:
        """Execute the full engine pipeline: validate → flow → validate output → return.

        GUARANTEES:
          - Never raises exceptions — always returns EngineOutput
          - Never mutates engine_input.data
          - Output is always a structured dict
        """
        import time

        start_time = time.monotonic()

        # 1. Validate & prepare input
        try:
            data = self.input_handler.prepare(engine_input)
        except ValueError as exc:
            self.logger.error("Input rejected: %s", exc)
            return EngineOutput(
                task_id=engine_input.task_id,
                engine_name=self.engine_name,
                status=EngineStatus.FAILED,
                error=str(exc),
            )

        # 2. Execute flow steps (catches all exceptions internally)
        try:
            step_results = self.flow.run(data)
        except Exception as exc:
            self.logger.error("Flow execution crashed: %s", exc)
            return EngineOutput(
                task_id=engine_input.task_id,
                engine_name=self.engine_name,
                status=EngineStatus.FAILED,
                error=f"Flow execution error: {exc}",
            )

        # 3. Build output
        try:
            output = self.output_handler.build_output(engine_input.task_id, step_results)
        except Exception as exc:
            self.logger.error("Output building failed: %s", exc)
            return EngineOutput(
                task_id=engine_input.task_id,
                engine_name=self.engine_name,
                status=EngineStatus.FAILED,
                error=f"Output build error: {exc}",
            )

        # 4. Validate output
        errors = self.validator.validate(output)
        if errors:
            output.status = EngineStatus.FAILED
            output.error = "; ".join(errors)

        elapsed = time.monotonic() - start_time
        self.logger.info("Engine run complete: status=%s elapsed=%.3fs", output.status.value, elapsed)

        # Record feedback for learning (read-only — never modifies engine code)
        if _feedback_store is not None:
            try:
                _feedback_store.record(
                    engine_name=self.engine_name,
                    task_id=engine_input.task_id,
                    status=output.status.value,
                    elapsed_seconds=elapsed,
                    input_summary=engine_input.data,
                    output_summary=output.result,
                    step_results=[s.__dict__ for s in output.steps] if output.steps else None,
                    error=output.error,
                )
            except Exception as fb_exc:
                self.logger.warning("Feedback recording failed (non-critical): %s", fb_exc)

        return output
