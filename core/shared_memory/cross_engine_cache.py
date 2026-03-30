"""CrossEngineCache — shared cache between engines for data reuse.

When pricing engine computes margin scores, inventory engine can reuse them.
When customer engine segments users, email engine uses those segments.
Avoids redundant computation across the engine fleet.
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("shared_memory.cache")


class CrossEngineCache:
    """Thread-safe cross-engine data cache with TTL."""

    _instance: CrossEngineCache | None = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> CrossEngineCache:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0, "stores": 0}
        self._initialized = True

    def store(self, engine_name: str, data_type: str, data: Any, ttl: int = 300) -> str:
        """Store data from one engine for others to use."""
        key = f"{engine_name}:{data_type}"
        with self._lock:
            self._cache[key] = {
                "data": copy.deepcopy(data),
                "source_engine": engine_name,
                "data_type": data_type,
                "stored_at": time.time(),
                "expires_at": time.time() + ttl,
            }
            self._stats["stores"] += 1
        return key

    def get(self, engine_name: str, data_type: str) -> Any | None:
        """Get cached data from a specific engine."""
        key = f"{engine_name}:{data_type}"
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None
            if time.time() > entry["expires_at"]:
                del self._cache[key]
                self._stats["misses"] += 1
                return None
            self._stats["hits"] += 1
            return copy.deepcopy(entry["data"])

    def get_by_type(self, data_type: str) -> list[dict[str, Any]]:
        """Get all cached entries of a specific type (from any engine)."""
        now = time.time()
        results = []
        with self._lock:
            for key, entry in list(self._cache.items()):
                if now > entry["expires_at"]:
                    del self._cache[key]
                    continue
                if entry["data_type"] == data_type:
                    results.append({
                        "source_engine": entry["source_engine"],
                        "data": copy.deepcopy(entry["data"]),
                        "age_seconds": round(now - entry["stored_at"], 1),
                    })
        return results

    def get_from_any(self, data_types: list[str]) -> dict[str, Any]:
        """Get first available data matching any of the types."""
        for dt in data_types:
            entries = self.get_by_type(dt)
            if entries:
                return entries[0]
        return {}

    def invalidate(self, engine_name: str, data_type: str | None = None) -> int:
        """Invalidate cache entries. Returns count of removed entries."""
        removed = 0
        with self._lock:
            keys_to_remove = []
            for key in self._cache:
                if data_type:
                    if key == f"{engine_name}:{data_type}":
                        keys_to_remove.append(key)
                elif key.startswith(f"{engine_name}:"):
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                del self._cache[key]
                removed += 1
        return removed

    def cleanup(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.time()
        removed = 0
        with self._lock:
            expired = [k for k, v in self._cache.items() if now > v["expires_at"]]
            for k in expired:
                del self._cache[k]
                removed += 1
        return removed

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            return {
                **self._stats,
                "hit_rate": round(self._stats["hits"] / total, 4) if total else 0,
                "cache_size": len(self._cache),
            }

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
