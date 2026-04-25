"""Rate limiter — token bucket + sliding-window caps.

The brain makes external calls: Shopify REST/GraphQL (capped at
2 req/s), Meta Ads (tight), Groq/Gemini/DeepSeek (hard quotas),
scrape endpoints (polite). A cycle that fires N calls in a burst
trips every provider's cap and the daemon slows to a crawl.

RateLimiter implements three strategies:

  • ``TokenBucket`` — refill at ``rate`` tokens / second up to
    ``capacity``. acquire(n) blocks (or soft-fails) until n tokens
    are available.
  • ``SlidingWindow`` — last-N-second count. allow() returns True
    only if under the cap.
  • ``CostBudget`` — cumulative spend tracker (LLM $ or Shopify
    credits). allow(cost) checks the remaining budget for the
    current window.

LimiterRegistry composes named limiters so a caller does:

  rate_limit("shopify_rest").acquire(1)    # blocks ≤ 1s if needed
  rate_limit("groq").budget(0.002)          # dollars

All pure Python, thread-safe. No external deps.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


# ── Token bucket ────────────────────────────────────────────

class TokenBucket:
    def __init__(
        self,
        rate_per_sec: float,
        capacity: float | None = None,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        self._rate = float(rate_per_sec)
        self._capacity = float(capacity if capacity is not None
                                 else rate_per_sec)
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(
            self._capacity, self._tokens + elapsed * self._rate,
        )

    def try_acquire(self, n: float = 1) -> bool:
        """Non-blocking: True if n tokens were granted."""
        with self._lock:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

    def acquire(
        self, n: float = 1, timeout: float = 5.0,
    ) -> bool:
        """Blocking with a hard timeout. Returns True on grant,
        False if the timeout elapsed."""
        deadline = time.monotonic() + float(timeout)
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= n:
                    self._tokens -= n
                    return True
                needed = n - self._tokens
                wait = needed / self._rate
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(wait, remaining, 0.05))

    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


# ── Sliding window ─────────────────────────────────────────

class SlidingWindow:
    def __init__(
        self, limit: int, window_s: float,
    ) -> None:
        if limit <= 0 or window_s <= 0:
            raise ValueError("limit and window_s must be > 0")
        self._limit = int(limit)
        self._window = float(window_s)
        self._events: list[float] = []
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self._window
            # Drop old entries
            self._events = [t for t in self._events if t >= cutoff]
            if len(self._events) >= self._limit:
                return False
            self._events.append(now)
            return True

    def count(self) -> int:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self._window
            self._events = [t for t in self._events if t >= cutoff]
            return len(self._events)


# ── Cost budget ─────────────────────────────────────────────

class CostBudget:
    def __init__(
        self, cap_per_window: float, window_s: float = 86_400,
    ) -> None:
        if cap_per_window <= 0 or window_s <= 0:
            raise ValueError("cap and window must be > 0")
        self._cap = float(cap_per_window)
        self._window = float(window_s)
        self._ledger: list[tuple[float, float]] = []  # (ts, cost)
        self._lock = threading.Lock()

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._window
        self._ledger = [
            (t, c) for t, c in self._ledger if t >= cutoff
        ]

    def allow(self, cost: float) -> bool:
        cost = float(cost)
        if cost < 0:
            return False
        with self._lock:
            self._prune()
            spent = sum(c for _, c in self._ledger)
            if spent + cost > self._cap:
                return False
            self._ledger.append((time.monotonic(), cost))
            return True

    def remaining(self) -> float:
        with self._lock:
            self._prune()
            spent = sum(c for _, c in self._ledger)
            return max(0.0, self._cap - spent)

    def spent(self) -> float:
        with self._lock:
            self._prune()
            return sum(c for _, c in self._ledger)


# ── Registry ────────────────────────────────────────────────

@dataclass
class LimiterSpec:
    bucket: TokenBucket | None = None
    window: SlidingWindow | None = None
    budget: CostBudget | None = None

    def can_call(self, *, cost: float = 0.0) -> bool:
        if self.bucket and not self.bucket.try_acquire():
            return False
        if self.window and not self.window.allow():
            return False
        if self.budget and cost > 0 and not self.budget.allow(cost):
            return False
        return True

    def acquire(self, timeout: float = 5.0, cost: float = 0.0) -> bool:
        if self.bucket and not self.bucket.acquire(timeout=timeout):
            return False
        if self.window and not self.window.allow():
            return False
        if self.budget and cost > 0 and not self.budget.allow(cost):
            return False
        return True


class LimiterRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, LimiterSpec] = {}
        self._lock = threading.Lock()
        self._install_defaults()

    def register(
        self,
        name: str,
        rate_per_sec: float | None = None,
        capacity: float | None = None,
        sliding_limit: int | None = None,
        sliding_window_s: float | None = None,
        budget_cap: float | None = None,
        budget_window_s: float | None = None,
    ) -> LimiterSpec:
        spec = LimiterSpec()
        if rate_per_sec is not None:
            spec.bucket = TokenBucket(
                rate_per_sec=rate_per_sec,
                capacity=capacity,
            )
        if sliding_limit is not None and sliding_window_s is not None:
            spec.window = SlidingWindow(
                limit=sliding_limit, window_s=sliding_window_s,
            )
        if budget_cap is not None:
            spec.budget = CostBudget(
                cap_per_window=budget_cap,
                window_s=budget_window_s or 86_400,
            )
        with self._lock:
            self._by_name[name] = spec
        return spec

    def get(self, name: str) -> LimiterSpec:
        with self._lock:
            if name not in self._by_name:
                # Defensive default: generous bucket so unknown
                # names don't crash callers that forgot to register.
                self._by_name[name] = LimiterSpec(
                    bucket=TokenBucket(10.0, 10.0),
                )
            return self._by_name[name]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = {}
            for name, spec in self._by_name.items():
                out[name] = {
                    "tokens_available": (
                        round(spec.bucket.available(), 2)
                        if spec.bucket else None
                    ),
                    "window_count": (
                        spec.window.count() if spec.window else None
                    ),
                    "budget_spent": (
                        round(spec.budget.spent(), 4)
                        if spec.budget else None
                    ),
                    "budget_remaining": (
                        round(spec.budget.remaining(), 4)
                        if spec.budget else None
                    ),
                }
            return out

    def _install_defaults(self) -> None:
        # Shopify REST: 2 req/s (steady state) with small burst.
        self.register(
            "shopify_rest",
            rate_per_sec=2.0, capacity=4.0,
        )
        # Meta Ads — conservative defaults
        self.register(
            "meta_ads",
            rate_per_sec=1.0, capacity=2.0,
        )
        # Groq / OpenRouter — tight QPM
        self.register(
            "groq",
            rate_per_sec=0.5, capacity=2.0,
            budget_cap=5.0, budget_window_s=86_400,
        )
        # Gemini Flash
        self.register(
            "gemini",
            rate_per_sec=0.5, capacity=2.0,
            budget_cap=5.0, budget_window_s=86_400,
        )
        # DeepSeek V3
        self.register(
            "deepseek",
            rate_per_sec=0.5, capacity=2.0,
            budget_cap=5.0, budget_window_s=86_400,
        )


# ── Singleton ────────────────────────────────────────────────

_REG_LOCK = threading.Lock()
_REGISTRY: LimiterRegistry | None = None


def registry() -> LimiterRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        with _REG_LOCK:
            if _REGISTRY is None:
                _REGISTRY = LimiterRegistry()
    return _REGISTRY


def rate_limit(name: str) -> LimiterSpec:
    """Short-hand for the registry."""
    return registry().get(name)
