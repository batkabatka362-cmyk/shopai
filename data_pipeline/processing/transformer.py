"""Data Transformer — transforms data structures for engine consumption."""
from __future__ import annotations
from typing import Any, Callable
from utils.logger import get_logger

logger = get_logger("data.transformer")


class DataTransformer:
    """Transforms data into engine-ready format."""

    def __init__(self) -> None:
        self._transforms: dict[str, Callable] = {}

    def register_transform(self, name: str, fn: Callable) -> None:
        self._transforms[name] = fn

    def transform(self, data: list[dict[str, Any]], transform_name: str | None = None) -> list[dict[str, Any]]:
        if transform_name and transform_name in self._transforms:
            fn = self._transforms[transform_name]
            data = [fn(record) for record in data]
        logger.info("Transformed %d records", len(data))
        return data

    @staticmethod
    def flatten(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        flat = {}
        for k, v in record.items():
            key = f"{prefix}_{k}" if prefix else k
            if isinstance(v, dict):
                flat.update(DataTransformer.flatten(v, key))
            else:
                flat[key] = v
        return flat
