"""Short-Term Cache -- TTL-based in-memory cache with LRU eviction."""
from __future__ import annotations

import time
from typing import Any


class ShortTermCache:
    """In-memory cache with per-key TTL and LRU eviction when full."""

    def __init__(self, max_size: int = 10000) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._max_size: int = max_size
        self._access_order: list[str] = []  # most-recently-used at end
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    # ---- Public API -------------------------------------------------------

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Store *value* under *key* with a TTL in seconds."""
        now = time.time()

        # If key already exists, remove from access order for re-insertion
        if key in self._cache:
            self._touch(key)
        else:
            # Evict LRU entries if at capacity
            while len(self._cache) >= self._max_size:
                self._evict_lru()
            self._access_order.append(key)

        self._cache[key] = {
            "value": value,
            "expires_at": now + ttl,
            "created_at": now,
        }

    def get(self, key: str) -> Any:
        """Return the cached value, or None if missing / expired."""
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None

        if time.time() > entry["expires_at"]:
            # Expired -- remove lazily
            self._remove_entry(key)
            self._misses += 1
            return None

        self._hits += 1
        self._touch(key)
        return entry["value"]

    def delete(self, key: str) -> bool:
        """Delete a key. Returns True if it existed."""
        if key not in self._cache:
            return False
        self._remove_entry(key)
        return True

    def clear(self) -> None:
        """Remove all entries."""
        self._cache.clear()
        self._access_order.clear()

    def exists(self, key: str) -> bool:
        """Check if *key* is present and not expired."""
        entry = self._cache.get(key)
        if entry is None:
            return False
        if time.time() > entry["expires_at"]:
            self._remove_entry(key)
            return False
        return True

    def get_stats(self) -> dict:
        """Return cache statistics."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
            "evictions": self._evictions,
            "max_size": self._max_size,
        }

    def _cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of entries removed."""
        now = time.time()
        expired_keys = [
            k for k, v in self._cache.items() if now > v["expires_at"]
        ]
        for k in expired_keys:
            self._remove_entry(k)
        return len(expired_keys)

    # ---- Private helpers --------------------------------------------------

    def _touch(self, key: str) -> None:
        """Move *key* to end of access order (most recently used)."""
        try:
            self._access_order.remove(key)
        except ValueError:
            pass
        self._access_order.append(key)

    def _remove_entry(self, key: str) -> None:
        """Remove a key from both cache and access order."""
        self._cache.pop(key, None)
        try:
            self._access_order.remove(key)
        except ValueError:
            pass

    def _evict_lru(self) -> None:
        """Evict the least-recently-used entry."""
        if not self._access_order:
            return
        lru_key = self._access_order.pop(0)
        self._cache.pop(lru_key, None)
        self._evictions += 1
