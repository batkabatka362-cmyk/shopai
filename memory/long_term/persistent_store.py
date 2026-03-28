"""Persistent Store — long-term knowledge persistence."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("memory.persistent")


class PersistentStore:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def save(self, key: str, value: Any, tags: list[str] | None = None) -> None:
        self._store[key] = {"value": value, "tags": tags or []}

    def load(self, key: str) -> Any | None:
        entry = self._store.get(key)
        return entry["value"] if entry else None

    def search_by_tag(self, tag: str) -> list[tuple[str, Any]]:
        return [(k, e["value"]) for k, e in self._store.items() if tag in e.get("tags", [])]

    def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    def size(self) -> int:
        return len(self._store)
