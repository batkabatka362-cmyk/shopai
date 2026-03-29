"""ExecutionCache — caches engine results to avoid redundant computation.

If same engine gets same input twice, return cached result instead of re-running.
Cache is keyed by: engine_name + hash(input_data).
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("performance.cache")


class ExecutionCache:
    """Thread-safe execution result cache with TTL and LRU eviction."""

    _instance: ExecutionCache | None = None
    _instance_lock = threading.Lock()

    def __new__(cls, max_size: int = 1000, default_ttl: int = 300) -> ExecutionCache:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init(max_size, default_ttl)
            return cls._instance

    def _init(self, max_size: int, default_ttl: int) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._access_order: list[str] = []
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0, "stores": 0, "evictions": 0}

    def get(self, engine_name: str, input_data: dict[str, Any]) -> dict[str, Any] | None:
        """Get cached result. Returns None on miss."""
        key = self._make_key(engine_name, input_data)
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
            # LRU: move to end
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)
            return copy.deepcopy(entry["result"])

    def store(self, engine_name: str, input_data: dict[str, Any], result: dict[str, Any], ttl: int | None = None) -> None:
        """Store a result in cache."""
        key = self._make_key(engine_name, input_data)
        with self._lock:
            # Evict if full
            while len(self._cache) >= self._max_size and self._access_order:
                oldest = self._access_order.pop(0)
                self._cache.pop(oldest, None)
                self._stats["evictions"] += 1

            self._cache[key] = {
                "result": copy.deepcopy(result),
                "engine": engine_name,
                "stored_at": time.time(),
                "expires_at": time.time() + (ttl or self._default_ttl),
            }
            self._access_order.append(key)
            self._stats["stores"] += 1

    def invalidate(self, engine_name: str | None = None) -> int:
        """Invalidate cache entries. Returns count removed."""
        with self._lock:
            if engine_name is None:
                count = len(self._cache)
                self._cache.clear()
                self._access_order.clear()
                return count

            keys = [k for k, v in self._cache.items() if v["engine"] == engine_name]
            for k in keys:
                del self._cache[k]
                if k in self._access_order:
                    self._access_order.remove(k)
            return len(keys)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            return {
                **self._stats,
                "hit_rate": round(self._stats["hits"] / total, 4) if total > 0 else 0,
                "size": len(self._cache),
                "max_size": self._max_size,
            }

    @staticmethod
    def _make_key(engine_name: str, input_data: dict[str, Any]) -> str:
        # Only hash non-internal fields for cache key
        filtered = {k: v for k, v in input_data.items() if not k.startswith("_")}
        content = json.dumps({"engine": engine_name, "data": filtered}, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:24]
