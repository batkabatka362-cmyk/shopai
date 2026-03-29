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


# Global hooks — set by orchestrator at startup
_feedback_store = None
_data_enricher = None
_pre_processor = None
_post_processor = None


def set_feedback_store(store) -> None:
    """Set the global feedback store for all engines."""
    global _feedback_store
    _feedback_store = store


def set_data_layers(enricher=None, pre_processor=None, post_processor=None) -> None:
    """Set the global data processing layers for all engines."""
    global _data_enricher, _pre_processor, _post_processor
    _data_enricher = enricher
    _pre_processor = pre_processor
    _post_processor = post_processor


class BaseEngine(ABC):
    """Abstract base for all ShopAI engines.

    Full pipeline:
      1. InputHandler: validate required fields
      2. DataEnricher: add computed stats (product_stats, customer_stats, etc.)
      3. PreProcessor: run business logic BEFORE model (scores, metrics)
      4. FlowController: execute steps (each calls model with enriched data)
      5. PostProcessor: clean model output into structured result
      6. OutputValidator: verify output completeness
      7. OutputHandler: format final response
      8. FeedbackStore: record for learning (read-only)

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
        """Execute the full engine pipeline with deep data processing.

        Pipeline: Validate → Enrich → PreProcess → Flow → PostProcess → Validate → Output → Learn

        GUARANTEES:
          - Never raises exceptions — always returns EngineOutput
          - Never mutates engine_input.data
          - Output is always a structured dict
          - Data flows: Raw → Clean → Enriched → Pre-computed → Model → Post-processed → Validated
        """
        import time

        start_time = time.monotonic()

        # 1. Validate & prepare input (creates copy — never mutates original)
        try:
            data = self.input_handler.prepare(engine_input)
        except ValueError as exc:
            self.logger.error("Input rejected: %s", exc)
            return self._fail_output(engine_input.task_id, str(exc), start_time)

        # 2. Enrich data with computed stats (product_stats, customer_stats, etc.)
        if _data_enricher is not None:
            try:
                data = _data_enricher.enrich(data, self.engine_name)
            except Exception as exc:
                self.logger.warning("Data enrichment failed (non-critical): %s", exc)

        # 3. Pre-process: run business logic BEFORE model (scores, metrics, etc.)
        if _pre_processor is not None:
            try:
                data = _pre_processor.process(data, self.engine_name, "analyze")
            except Exception as exc:
                self.logger.warning("Pre-processing failed (non-critical): %s", exc)

        # 4. Execute flow steps (each step calls model with enriched+pre-computed data)
        try:
            step_results = self.flow.run(data)
        except Exception as exc:
            self.logger.error("Flow execution crashed: %s", exc)
            return self._fail_output(engine_input.task_id, f"Flow execution error: {exc}", start_time)

        # 5. Post-process: clean model output into structured result
        if _post_processor is not None and step_results:
            try:
                for step_result in step_results:
                    if step_result.output and step_result.status == EngineStatus.COMPLETED:
                        step_result.output = _post_processor.process(
                            step_result.output, step_result.step_name, self.engine_name
                        )
            except Exception as exc:
                self.logger.warning("Post-processing failed (non-critical): %s", exc)

        # 6. Build output
        try:
            output = self.output_handler.build_output(engine_input.task_id, step_results)
        except Exception as exc:
            self.logger.error("Output building failed: %s", exc)
            return self._fail_output(engine_input.task_id, f"Output build error: {exc}", start_time)

        # 7. Validate output
        errors = self.validator.validate(output)
        if errors:
            output.status = EngineStatus.FAILED
            output.error = "; ".join(errors)

        elapsed = time.monotonic() - start_time
        self.logger.info("Engine run complete: status=%s elapsed=%.3fs", output.status.value, elapsed)

        # 8. Record feedback for learning (read-only — never modifies engine code)
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

    def _fail_output(self, task_id: str, error: str, start_time: float) -> EngineOutput:
        """Create a failed output with timing."""
        import time
        elapsed = time.monotonic() - start_time
        self.logger.error("Engine failed in %.3fs: %s", elapsed, error)
        return EngineOutput(
            task_id=task_id,
            engine_name=self.engine_name,
            status=EngineStatus.FAILED,
            error=error,
        )
