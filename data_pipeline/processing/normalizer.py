"""Data Normalizer — normalizes values, scales, and formats."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("data.normalizer")


class DataNormalizer:
    """Normalizes data to consistent formats and scales."""

    def normalize(self, data: list[dict[str, Any]], schema: dict[str, str] | None = None) -> list[dict[str, Any]]:
        logger.info("Normalizing %d records", len(data))
        normalized = []
        for record in data:
            if schema:
                record = self._apply_schema(record, schema)
            normalized.append(record)
        return normalized

    @staticmethod
    def _apply_schema(record: dict[str, Any], schema: dict[str, str]) -> dict[str, Any]:
        result = {}
        for key, dtype in schema.items():
            val = record.get(key)
            if val is None:
                result[key] = None
            elif dtype == "float":
                result[key] = float(val) if val else 0.0
            elif dtype == "int":
                result[key] = int(float(val)) if val else 0
            elif dtype == "str":
                result[key] = str(val)
            else:
                result[key] = val
        return result
