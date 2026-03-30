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

    # Field aliases: different engines may use different names for the same data
    FIELD_ALIASES: dict[str, list[str]] = {
        "products": ["product_data", "product_catalog", "product_list", "items"],
        "product_data": ["products", "product_catalog", "product_list", "items"],
        "customer_data": ["customers", "customer_list", "audience_data", "user_data"],
        "order_data": ["orders", "order_list", "transaction_data"],
        "campaign_data": ["campaign", "campaign_config", "marketing_data"],
        "inventory_data": ["inventory", "stock_data", "items"],
        "keyword_data": ["keywords", "seed_keywords", "search_data"],
        "criteria": ["config", "criteria_config", "filter_config", "scoring_criteria"],
        "site_data": ["page_data", "website_data", "url_data"],
    }

    def validate(self, engine_input: EngineInput) -> list[str]:
        """Return list of validation errors. Empty list = valid.

        Smart validation: checks required fields AND their aliases.
        If data has any alias of a required field, it's considered valid.
        """
        errors: list[str] = []

        if not engine_input.data:
            errors.append("Input data is empty")
            return errors

        for field_name in self._required_fields:
            if self._field_or_alias_exists(field_name, engine_input.data):
                continue
            errors.append(f"Missing required field: {field_name}")

        return errors

    def prepare(self, engine_input: EngineInput) -> dict[str, Any]:
        """Extract and return the validated data payload for processing.

        Smart preparation: if data has an alias of a required field,
        copies it to the canonical name so the engine can find it.
        """
        errors = self.validate(engine_input)
        if errors:
            # Soft mode: if data has SOME fields, proceed with warning
            non_empty = sum(1 for v in engine_input.data.values() if v is not None and v != {} and v != [])
            if non_empty > 0:
                logger.warning("[%s] Input validation soft-pass: %s (has %d non-empty fields)",
                               self._engine_name, "; ".join(errors), non_empty)
            else:
                raise ValueError(
                    f"[{self._engine_name}] Input validation failed: {'; '.join(errors)}"
                )

        data = dict(engine_input.data)

        # Resolve aliases: copy alias values to canonical names
        for field_name in self._required_fields:
            if field_name not in data:
                for alias in self.FIELD_ALIASES.get(field_name, []):
                    if alias in data:
                        data[field_name] = data[alias]
                        break

        logger.info("[%s] Input validated: %d fields", self._engine_name, len(data))
        return data

    def _field_or_alias_exists(self, field_name: str, data: dict[str, Any]) -> bool:
        """Check if field or any of its aliases exist in data."""
        if field_name in data:
            return True
        for alias in self.FIELD_ALIASES.get(field_name, []):
            if alias in data:
                return True
        return False
