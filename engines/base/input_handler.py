"""Input Handler — validates and prepares structured input for the engine.

Responsibility: Ensure the engine only receives valid, structured data.
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger
from .engine_types import EngineInput

logger = get_logger("engine.input_handler")


class InputHandler:
    """Validates incoming data against required fields and types."""

    def __init__(self, engine_name: str, required_fields: list[str] | None = None) -> None:
        self._engine_name = engine_name
        self._required_fields = required_fields or []

    def validate(self, engine_input: EngineInput) -> list[str]:
        """Return list of validation errors. Empty list = valid."""
        errors: list[str] = []

        if not engine_input.data:
            errors.append("Input data is empty")
            return errors

        for field_name in self._required_fields:
            if field_name not in engine_input.data:
                errors.append(f"Missing required field: {field_name}")

        return errors

    def prepare(self, engine_input: EngineInput) -> dict[str, Any]:
        """Extract and return the validated data payload for processing."""
        errors = self.validate(engine_input)
        if errors:
            raise ValueError(
                f"[{self._engine_name}] Input validation failed: {'; '.join(errors)}"
            )
        logger.info("[%s] Input validated: %d fields", self._engine_name, len(engine_input.data))
        return dict(engine_input.data)
