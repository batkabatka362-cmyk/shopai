"""FairScheduler — fair resource sharing between engines."""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("rate_limiter.fair")


class FairScheduler:
    """Ensures fair model access between competing engines."""

    def __init__(self, max_concurrent: int = 5) -> None:
        self._semaphore = threading.Semaphore(max_concurrent)
        self._active: dict[str, int] = {}
        self._wait_times: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def acquire(self, engine_name: str, timeout: float = 30) -> bool:
        """Acquire execution slot. Returns True if acquired within timeout."""
        start = time.monotonic()
        acquired = self._semaphore.acquire(timeout=timeout)
        wait = time.monotonic() - start

        with self._lock:
            self._active[engine_name] = self._active.get(engine_name, 0) + 1
            self._wait_times.setdefault(engine_name, []).append(wait)
            if len(self._wait_times[engine_name]) > 1000:
                self._wait_times[engine_name] = self._wait_times[engine_name][-1000:]

        if not acquired:
            logger.warning("Engine '%s' timed out waiting for execution slot", engine_name)
        return acquired

    def release(self, engine_name: str) -> None:
        """Release execution slot."""
        self._semaphore.release()
        with self._lock:
            self._active[engine_name] = max(0, self._active.get(engine_name, 1) - 1)

    def get_active(self) -> dict[str, int]:
        with self._lock:
            return dict(self._active)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            stats = {}
            for engine, waits in self._wait_times.items():
                if waits:
                    stats[engine] = {
                        "avg_wait_ms": round(sum(waits) / len(waits) * 1000, 2),
                        "max_wait_ms": round(max(waits) * 1000, 2),
                        "total_requests": len(waits),
                        "active_now": self._active.get(engine, 0),
                    }
            return stats
