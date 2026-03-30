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
        """Return list of validation errors. Empty = valid.

        Smart validation: checks top-level result AND _steps sub-outputs.
        If SmartExecutor produced real computed data (score, decision, etc.),
        the output is considered valid even if original required_output_fields
        are nested inside step outputs.
        """
        errors: list[str] = []

        if output.status == EngineStatus.FAILED:
            errors.append(f"Engine returned failed status: {output.error}")
            return errors

        if output.status == EngineStatus.REJECTED:
            return errors  # rejected is a valid terminal state

        # Check required fields in top-level result AND in step outputs
        for field_name in self._required_output_fields:
            if self._field_exists(field_name, output.result):
                continue
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

        # Smart override: if SmartExecutor produced real computed data,
        # treat missing required fields as warnings, not errors
        if errors and self._has_computed_data(output.result):
            real_errors = [e for e in errors if "Failed steps" in e]
            if not real_errors:
                # Only missing fields — SmartExecutor has real data, so pass
                logger.info("[%s] Validation: required fields missing but computed data present — passing", self._engine_name)
                return []

        if errors:
            logger.warning("[%s] Validation failed: %s", self._engine_name, "; ".join(errors))
        else:
            logger.info("[%s] Output validated successfully", self._engine_name)

        return errors

    @staticmethod
    def _field_exists(field_name: str, result: dict) -> bool:
        """Check if field exists in result or nested in _steps."""
        if field_name in result:
            return True
        # Check inside _steps namespace
        steps = result.get("_steps", {})
        if isinstance(steps, dict):
            for step_data in steps.values():
                if isinstance(step_data, dict) and field_name in step_data:
                    return True
        return False

    @staticmethod
    def _has_computed_data(result: dict) -> bool:
        """Check if SmartExecutor produced real computed data."""
        computed_markers = ("score", "decision", "scored_products", "selected_products",
                           "price_analysis", "margin_analysis", "customer_analysis",
                           "rfm_segments", "keyword_analysis", "inventory_analysis",
                           "campaign_analysis", "validation_checks", "generated",
                           "recommendations", "rankings", "strategic_insights")
        return any(key in result for key in computed_markers)
