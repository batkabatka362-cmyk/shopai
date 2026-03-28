"""Data Validator — validates data integrity and completeness."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("data.validator")


class DataValidator:
    """Validates data against rules and schemas."""

    def __init__(self, required_fields: list[str] | None = None) -> None:
        self._required_fields = required_fields or []

    def validate(self, data: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        valid, invalid = [], []
        for record in data:
            errors = self._check_record(record)
            if errors:
                record["_validation_errors"] = errors
                invalid.append(record)
            else:
                valid.append(record)
        logger.info("Validated: %d valid, %d invalid", len(valid), len(invalid))
        return valid, invalid

    def _check_record(self, record: dict[str, Any]) -> list[str]:
        errors = []
        for field in self._required_fields:
            if field not in record or record[field] is None:
                errors.append(f"Missing: {field}")
        return errors
