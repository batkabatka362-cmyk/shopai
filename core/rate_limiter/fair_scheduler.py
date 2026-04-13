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
        if not isinstance(max_concurrent, int) or max_concurrent <= 0:
            max_concurrent = 5
        self._max_concurrent = max_concurrent
        self._semaphore = threading.Semaphore(max_concurrent)
        self._active: dict[str, int] = {}
        self._wait_times: dict[str, list[float]] = {}
        # Track which engines currently hold a slot so release()
        # can reject a release-without-acquire. Pre-audit a
        # stray ``release("foo")`` incremented the semaphore
        # above ``max_concurrent`` permanently, breaking the
        # fairness invariant. Audit pass 53.
        self._held: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, engine_name: str, timeout: float = 30) -> bool:
        """Acquire execution slot. Returns True if acquired within timeout.

        Pre-audit bug: stats were incremented BEFORE checking
        ``acquired`` — a failed acquire still counted as an
        active slot, corrupting ``active_now`` in stats and
        leaking a phantom slot per timeout. Audit pass 53.
        """
        if not isinstance(engine_name, str):
            engine_name = str(engine_name) if engine_name is not None else "unknown"
        start = time.monotonic()
        acquired = self._semaphore.acquire(timeout=timeout)
        wait = time.monotonic() - start

        with self._lock:
            # Always record the wait time regardless of outcome
            # — it's a performance signal.
            self._wait_times.setdefault(engine_name, []).append(wait)
            if len(self._wait_times[engine_name]) > 1000:
                del self._wait_times[engine_name][:len(self._wait_times[engine_name]) - 1000]
            if acquired:
                self._active[engine_name] = self._active.get(engine_name, 0) + 1
                self._held[engine_name] = self._held.get(engine_name, 0) + 1

        if not acquired:
            logger.warning("Engine '%s' timed out waiting for execution slot", engine_name)
        return acquired

    def release(self, engine_name: str) -> None:
        """Release execution slot.

        Pre-audit unconditionally released the semaphore, so a
        caller that released without acquiring (or released
        twice) inflated the semaphore count above
        ``max_concurrent`` — permanently breaking the
        concurrency cap. Now we only release if this engine
        actually holds a slot. Audit pass 53.
        """
        if not isinstance(engine_name, str):
            engine_name = str(engine_name) if engine_name is not None else "unknown"
        with self._lock:
            held = self._held.get(engine_name, 0)
            if held <= 0:
                logger.warning(
                    "FairScheduler: release('%s') without matching acquire — ignored",
                    engine_name,
                )
                return
            self._held[engine_name] = held - 1
            self._active[engine_name] = max(0, self._active.get(engine_name, 1) - 1)
        self._semaphore.release()

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
