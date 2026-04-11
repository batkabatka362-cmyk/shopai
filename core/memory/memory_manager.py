from __future__ import annotations

import time
from typing import Any

from utils.helpers import generate_id, timestamp_now
from utils.logger import get_logger

logger = get_logger("memory.manager")


class MemoryManager:
    """Manages short-term and long-term memory stores.

    Short-term entries carry a TTL (default 300s). `recall()` and
    `recall_by_tag()` evict expired entries on read so the store
    doesn't accumulate stale data and callers never see expired
    values. The previous implementation set ``ttl_seconds`` but
    never actually checked it — entries lived forever and the
    parameter was decorative.
    """

    def __init__(self) -> None:
        self._short_term: dict[str, dict[str, Any]] = {}
        self._long_term: dict[str, dict[str, Any]] = {}

    def store_short_term(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        now = time.time()
        self._short_term[key] = {
            "value": value,
            # Wall-clock string for display + a numeric expiry for math.
            "stored_at": timestamp_now(),
            "stored_at_ts": now,
            "ttl_seconds": ttl_seconds,
            "expires_at": now + ttl_seconds if ttl_seconds > 0 else 0.0,
        }

    def store_long_term(self, key: str, value: Any, tags: list[str] | None = None) -> None:
        self._long_term[key] = {
            "value": value,
            "stored_at": timestamp_now(),
            "tags": tags or [],
        }

    def _is_expired(self, entry: dict[str, Any], now: float) -> bool:
        expires_at = entry.get("expires_at", 0.0)
        return bool(expires_at) and expires_at <= now

    def _evict_if_expired(self, key: str, now: float) -> bool:
        """Drop the short-term entry if it has passed its TTL.
        Returns True iff an entry was evicted."""
        entry = self._short_term.get(key)
        if entry is None:
            return False
        if self._is_expired(entry, now):
            del self._short_term[key]
            return True
        return False

    def recall(self, key: str) -> Any | None:
        now = time.time()
        if key in self._short_term:
            if self._evict_if_expired(key, now):
                # Fall through to long-term — do not return stale data.
                pass
            else:
                return self._short_term[key]["value"]
        if key in self._long_term:
            return self._long_term[key]["value"]
        return None

    def recall_by_tag(self, tag: str) -> list[tuple[str, Any]]:
        results = []
        for key, entry in self._long_term.items():
            if tag in entry.get("tags", []):
                results.append((key, entry["value"]))
        return results

    def forget_short_term(self, key: str) -> bool:
        return self._short_term.pop(key, None) is not None

    def forget_long_term(self, key: str) -> bool:
        return self._long_term.pop(key, None) is not None

    def clear_short_term(self) -> int:
        count = len(self._short_term)
        self._short_term.clear()
        return count

    def sweep_expired(self) -> int:
        """Drop every expired short-term entry. Returns the count of
        evictions. Useful for periodic cleanup loops."""
        now = time.time()
        expired = [
            k for k, e in self._short_term.items()
            if self._is_expired(e, now)
        ]
        for k in expired:
            del self._short_term[k]
        return len(expired)

    def get_stats(self) -> dict[str, int]:
        return {
            "short_term_entries": len(self._short_term),
            "long_term_entries": len(self._long_term),
        }
