"""Retry policy — exponential backoff + circuit breaker.

rate_limiter (v13-D2) throttles *how often* we call external
providers. It doesn't handle *failures*. When Meta Ads returns 503
for ten minutes straight, the daemon previously kept hammering
and got every cycle rejected.

RetryPolicy combines two classic patterns:

  • Exponential backoff with jitter — retry delay = base · 2^n +
    U(0, jitter). Callers pick max_attempts.
  • Circuit breaker — after ``failure_threshold`` failures in the
    last ``failure_window_s`` the circuit opens. While open, calls
    short-circuit with a BreakerOpen exception (no actual call).
    After ``reset_after_s`` the circuit half-opens: one probe call
    decides whether to close or stay open.

APIs:

  @retry("meta_ads") def fetch(...): ...
  retry("meta_ads").call(fn, *args)
  retry("meta_ads").is_open() / reset()

Integrates with rate_limiter: the decorator optionally acquires a
token first, so one decorator handles both failure and rate.

Pure stdlib, thread-safe. No external deps.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("system.retry")


class BreakerOpen(RuntimeError):
    """Raised when the circuit breaker is open."""


@dataclass
class RetrySpec:
    name: str
    max_attempts: int = 3
    base_delay_s: float = 0.1
    max_delay_s: float = 5.0
    jitter_s: float = 0.1
    failure_threshold: int = 5
    failure_window_s: float = 60.0
    reset_after_s: float = 30.0

    # Internal breaker state
    _failures: list[float] = field(default_factory=list)
    _opened_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _record_failure(self) -> None:
        now = time.time()
        with self._lock:
            self._failures = [
                t for t in self._failures
                if now - t <= self.failure_window_s
            ]
            self._failures.append(now)
            if (len(self._failures) >= self.failure_threshold
                    and self._opened_at is None):
                self._opened_at = now
                logger.warning("circuit opened for %s", self.name)

    def _record_success(self) -> None:
        with self._lock:
            self._failures = []
            if self._opened_at is not None:
                logger.info("circuit closed for %s", self.name)
            self._opened_at = None

    def _breaker_state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if (time.time() - self._opened_at) > self.reset_after_s:
                return "half_open"
            return "open"

    # ── Decorator / call wrappers ──────────────────────────

    def call(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_attempt: Callable[[int, Exception], None] | None = None,
        **kwargs: Any,
    ) -> Any:
        state = self._breaker_state()
        if state == "open":
            raise BreakerOpen(
                f"{self.name}: circuit open, refusing to call",
            )
        last_exc: Exception | None = None
        attempts = 1 if state == "half_open" else self.max_attempts
        for attempt in range(1, attempts + 1):
            try:
                result = fn(*args, **kwargs)
                self._record_success()
                return result
            except Exception as exc:
                last_exc = exc
                self._record_failure()
                if on_attempt:
                    try:
                        on_attempt(attempt, exc)
                    except Exception as cb_exc:
                        logger.debug(
                            "on_attempt callback raised: %s", cb_exc,
                        )
                if attempt == attempts:
                    break
                delay = self._delay(attempt)
                time.sleep(delay)
        # All attempts failed
        raise last_exc or RuntimeError("retry exhausted")

    def _delay(self, attempt: int) -> float:
        import math
        base = self.base_delay_s * (2 ** (attempt - 1))
        capped = min(self.max_delay_s, base)
        jitter = random.uniform(0.0, self.jitter_s)
        return capped + jitter

    def is_open(self) -> bool:
        return self._breaker_state() == "open"

    def reset(self) -> None:
        with self._lock:
            self._failures = []
            self._opened_at = None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            recent = [
                t for t in self._failures
                if now - t <= self.failure_window_s
            ]
        return {
            "name": self.name,
            "state": self._breaker_state(),
            "recent_failures": len(recent),
            "opened_at": self._opened_at,
            "max_attempts": self.max_attempts,
        }


# ── Registry ────────────────────────────────────────────────

class RetryRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, RetrySpec] = {}
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        max_attempts: int = 3,
        base_delay_s: float = 0.1,
        max_delay_s: float = 5.0,
        jitter_s: float = 0.1,
        failure_threshold: int = 5,
        failure_window_s: float = 60.0,
        reset_after_s: float = 30.0,
    ) -> RetrySpec:
        with self._lock:
            spec = RetrySpec(
                name=name,
                max_attempts=max_attempts,
                base_delay_s=base_delay_s,
                max_delay_s=max_delay_s,
                jitter_s=jitter_s,
                failure_threshold=failure_threshold,
                failure_window_s=failure_window_s,
                reset_after_s=reset_after_s,
            )
            self._by_name[name] = spec
            return spec

    def get(self, name: str) -> RetrySpec:
        with self._lock:
            if name not in self._by_name:
                self._by_name[name] = RetrySpec(name=name)
            return self._by_name[name]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {n: s.stats() for n, s in self._by_name.items()}


_REG_LOCK = threading.Lock()
_REGISTRY: RetryRegistry | None = None


def registry() -> RetryRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REG_LOCK:
            if _REGISTRY is None:
                _REGISTRY = RetryRegistry()
    return _REGISTRY


def retry(name: str) -> RetrySpec:
    """Short-hand: ``retry('meta_ads').call(fn, ...)``."""
    return registry().get(name)


# ── Decorator ──────────────────────────────────────────────

def with_retry(name: str):
    """Decorator form: wraps a callable with the named RetrySpec."""
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        spec = registry().get(name)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            return spec.call(fn, *args, **kwargs)
        wrapped.__name__ = getattr(fn, "__name__", "wrapped")
        wrapped.__doc__ = getattr(fn, "__doc__", None)
        return wrapped
    return deco
