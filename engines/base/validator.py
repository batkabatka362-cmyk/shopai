"""Output Validator — checks final output quality and consistency.

Responsibility: Ensure engine output meets quality standards before returning.
Validation is the last gate before output leaves the engine.
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from .engine_types import EngineOutput, EngineStatus

logger = get_logger("engine.validator")


class OutputValidator:
    """Validates structured engine output against required output fields."""

    def __init__(self, engine_name: str, required_output_fields: list[str] | None = None) -> None:
        self._engine_name = engine_name
        self._required_output_fields = required_output_fields or []

    def validate(self, output: EngineOutput) -> list[str]:
        """Return list of validation errors. Empty = valid."""
        errors: list[str] = []

        if output.status == EngineStatus.FAILED:
            errors.append(f"Engine returned failed status: {output.error}")
            return errors

        if output.status == EngineStatus.REJECTED:
            return errors  # rejected is a valid terminal state

        for field_name in self._required_output_fields:
            if field_name not in output.result:
                errors.append(f"Missing required output field: {field_name}")

        if not output.steps:
            errors.append("No execution steps recorded")

        failed_required = [
            s for s in output.steps
            if s.status == EngineStatus.FAILED
        ]
        if failed_required:
            step_names = ", ".join(s.step_name for s in failed_required)
            errors.append(f"Failed steps: {step_names}")

        if errors:
            logger.warning("[%s] Validation failed: %s", self._engine_name, "; ".join(errors))
        else:
            logger.info("[%s] Output validated successfully", self._engine_name)

        return errors
