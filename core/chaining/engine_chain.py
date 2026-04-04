"""EngineChain — executes a sequence of engines where output flows to next input.

Chain rule: Engine A output → transform → Engine B input → ... → final output.
Each engine in the chain runs independently. Never modifies engine code.
"""
from __future__ import annotations

import copy
import time
from typing import Any, Callable

from utils.logger import get_logger
from utils.helpers import generate_id
from engines.registry import get_engine
from engines.base.engine_types import EngineInput, EngineStatus, normalize_engine_output

logger = get_logger("chaining.engine_chain")

# Transform function: takes previous output + chain context, returns next input data
OutputTransform = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def passthrough_transform(output: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Default: pass all output fields as next input."""
    merged = copy.deepcopy(context)
    merged.update(output)
    return merged


class ChainStep:
    """One step in an engine chain."""

    __slots__ = ("engine_name", "transform", "required", "description")

    def __init__(
        self,
        engine_name: str,
        transform: OutputTransform | None = None,
        required: bool = True,
        description: str = "",
    ) -> None:
        self.engine_name = engine_name
        self.transform = transform or passthrough_transform
        self.required = required
        self.description = description


class EngineChain:
    """Executes engines in sequence, piping output → input.

    RULES:
      - Never modifies engine code or structure
      - Deep copies data between steps (no mutation)
      - Stops on failure if step is required
      - Returns structured result with full step history
    """

    def __init__(self, name: str, steps: list[ChainStep] | None = None) -> None:
        self.name = name
        self._steps: list[ChainStep] = steps or []

    def add_step(
        self,
        engine_name: str,
        transform: OutputTransform | None = None,
        required: bool = True,
        description: str = "",
    ) -> "EngineChain":
        self._steps.append(ChainStep(engine_name, transform, required, description))
        return self

    def run(self, initial_data: dict[str, Any]) -> dict[str, Any]:
        """Execute the full chain. Returns structured result."""
        chain_id = generate_id("chain")
        start_time = time.monotonic()
        context = copy.deepcopy(initial_data)
        step_results = []
        final_output = {}

        logger.info("Chain '%s' started (id=%s, steps=%d)", self.name, chain_id, len(self._steps))

        for i, step in enumerate(self._steps):
            step_start = time.monotonic()

            # Prepare input for this engine
            try:
                engine_data = step.transform(final_output, context)
            except Exception as exc:
                step_results.append(self._step_error(step, i, f"Transform failed: {exc}"))
                if step.required:
                    break
                continue

            # Run engine
            try:
                engine = get_engine(step.engine_name)
                engine_input = EngineInput(
                    task_id=f"{chain_id}_step{i}",
                    engine_name=step.engine_name,
                    data=engine_data,
                )
                raw_output = engine.run(engine_input)
                output = normalize_engine_output(raw_output, engine_input)
            except Exception as exc:
                step_results.append(self._step_error(step, i, f"Engine error: {exc}"))
                if step.required:
                    break
                continue

            step_elapsed = time.monotonic() - step_start
            step_result = {
                "step_index": i,
                "engine": step.engine_name,
                "status": output.status.value,
                "elapsed_seconds": round(step_elapsed, 3),
                "output_keys": list(output.result.keys()) if output.result else [],
                "error": output.error,
            }
            step_results.append(step_result)

            if output.status == EngineStatus.COMPLETED:
                final_output = copy.deepcopy(output.result)
                context.update(final_output)
            elif step.required:
                logger.error("Chain '%s' stopped: required step %d (%s) failed",
                             self.name, i, step.engine_name)
                break

        total_elapsed = time.monotonic() - start_time
        completed_steps = sum(1 for s in step_results if s.get("status") == "completed")
        chain_status = "completed" if completed_steps == len(self._steps) else "partial" if completed_steps > 0 else "failed"

        result = {
            "chain_id": chain_id,
            "chain_name": self.name,
            "status": chain_status,
            "total_steps": len(self._steps),
            "completed_steps": completed_steps,
            "elapsed_seconds": round(total_elapsed, 3),
            "steps": step_results,
            "final_output": final_output,
        }

        logger.info("Chain '%s' finished: status=%s (%d/%d steps, %.3fs)",
                     self.name, chain_status, completed_steps, len(self._steps), total_elapsed)
        return result

    @staticmethod
    def _step_error(step: ChainStep, index: int, error: str) -> dict[str, Any]:
        return {
            "step_index": index,
            "engine": step.engine_name,
            "status": "failed",
            "elapsed_seconds": 0,
            "output_keys": [],
            "error": error,
        }
