"""Data Cleaner — removes noise, fixes formats, handles missing values."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("data.cleaner")


class DataCleaner:
    """Cleans raw data before processing."""

    def clean(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        logger.info("Cleaning %d records", len(data))
        cleaned = []
        for record in data:
            record = self._remove_nulls(record)
            record = self._strip_strings(record)
            cleaned.append(record)
        return cleaned

    @staticmethod
    def _remove_nulls(record: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in record.items() if v is not None}

    @staticmethod
    def _strip_strings(record: dict[str, Any]) -> dict[str, Any]:
        return {k: v.strip() if isinstance(v, str) else v for k, v in record.items()}
