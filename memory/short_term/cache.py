"""Short-Term Cache — TTL-based in-memory cache."""
from __future__ import annotations
from typing import Any
from utils.helpers import timestamp_now
from utils.logger import get_logger

logger = get_logger("memory.cache")


class ShortTermCache:
    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        self._cache[key] = {"value": value, "ttl": ttl_seconds, "created": timestamp_now()}

    def get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        return entry["value"] if entry else None

    def delete(self, key: str) -> bool:
        return self._cache.pop(key, None) is not None

    def clear(self) -> int:
        count = len(self._cache)
        self._cache.clear()
        return count

    def size(self) -> int:
        return len(self._cache)
