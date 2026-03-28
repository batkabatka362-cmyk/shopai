"""Feature Store — stores and retrieves computed features."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("data.feature_store")


class FeatureStore:
    """In-memory feature store for computed features."""

    def __init__(self) -> None:
        self._store: dict[str, list[dict[str, Any]]] = {}

    def save(self, key: str, features: list[dict[str, Any]]) -> None:
        self._store[key] = features
        logger.info("Stored features: %s (%d records)", key, len(features))

    def load(self, key: str) -> list[dict[str, Any]]:
        return self._store.get(key, [])

    def list_keys(self) -> list[str]:
        return list(self._store.keys())
