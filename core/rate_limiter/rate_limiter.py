"""RateLimiter — token bucket rate limiting per engine and model."""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("rate_limiter")


class RateLimiter:
    """Token bucket rate limiter. Thread-safe."""

    def __init__(self) -> None:
        self._buckets: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stats = {"allowed": 0, "denied": 0}

    def configure(self, key: str, rate: float, burst: int = 10) -> None:
        """Configure rate limit: rate=tokens/second, burst=max tokens."""
        with self._lock:
            self._buckets[key] = {
                "rate": rate,
                "burst": burst,
                "tokens": float(burst),
                "last_refill": time.monotonic(),
            }

    def allow(self, key: str) -> bool:
        """Check if request is allowed. Consumes 1 token."""
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                self._stats["allowed"] += 1
                return True  # No limit configured

            self._refill(bucket)
            if bucket["tokens"] >= 1:
                bucket["tokens"] -= 1
                self._stats["allowed"] += 1
                return True

            self._stats["denied"] += 1
            return False

    def wait_and_allow(self, key: str, timeout: float = 5.0) -> bool:
        """Wait until a token is available or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.allow(key):
                return True
            time.sleep(0.05)
        return False

    def get_remaining(self, key: str) -> dict[str, Any]:
        """Get remaining tokens and rate info."""
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return {"key": key, "limited": False}
            self._refill(bucket)
            return {
                "key": key,
                "limited": True,
                "remaining_tokens": round(bucket["tokens"], 1),
                "rate_per_second": bucket["rate"],
                "burst": bucket["burst"],
            }

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._stats["allowed"] + self._stats["denied"]
            return {
                **self._stats,
                "deny_rate": round(self._stats["denied"] / total, 4) if total else 0,
                "configured_limits": len(self._buckets),
            }

    @staticmethod
    def _refill(bucket: dict) -> None:
        now = time.monotonic()
        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(bucket["burst"], bucket["tokens"] + elapsed * bucket["rate"])
        bucket["last_refill"] = now
