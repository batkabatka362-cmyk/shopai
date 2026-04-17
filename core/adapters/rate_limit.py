"""Adapter rate limiter — Option U.

The router already protects downstream vendors with a circuit breaker
(Option R), latency SLA monitoring (Option S), and cost budgets
(Option T). What was still missing is a **proactive** rate limiter.
Without one, the router happily submits 120 calls to OpenAI's 60/min
tier, the vendor rejects the overflow with HTTP 429, the retry policy
burns 3 extra attempts per rejected call, and the budget ledger
still records the cost of partial responses. Declaring the vendor
limit up front turns "rejected and retried" into "paced and served".

This module supplies three small primitives:

* ``RateLimit`` — declarative policy: ``requests_per_min``,
  ``requests_per_hour``, optional ``concurrent`` cap.
* ``TokenBucket`` — thread-safe bucket with a float refill rate and
  integer capacity. Checking costs one lock acquire; no sleep on the
  hot path. The router decides whether to queue, skip, or fail over.
* ``RateLimiter`` — per-adapter registry of buckets (one per window),
  plus a default catalog tuned for well-known vendors. Exposes a
  ``can_call()`` gate that returns a ``RateLimitDecision`` and a
  ``record()`` hook that consumes a token after a successful call.

The limiter is **opt-in** — an adapter with no policy registered is
always allowed. The default catalog covers the common paid tiers
(OpenAI 500/min, Anthropic 50/min, Groq 30/min, Shopify 2/s, etc.)
so configuring nothing still gives sensible behaviour on day one.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Policy ─────────────────────────────────────────────────────


@dataclass
class RateLimit:
    """Declarative per-adapter rate limit.

    Every field is optional — ``None`` disables that window. The
    limiter composes windows with logical AND: a call is allowed
    only if *every* configured bucket has capacity.
    """

    requests_per_min: int | None = None
    requests_per_hour: int | None = None

    #: Hard ceiling on simultaneous in-flight calls. Enforced by the
    #: router via ``acquire_slot`` / ``release_slot``. ``None`` = no cap.
    concurrent: int | None = None

    def __post_init__(self) -> None:
        if self.requests_per_min is not None and self.requests_per_min < 1:
            raise ValueError("requests_per_min must be >= 1")
        if self.requests_per_hour is not None and self.requests_per_hour < 1:
            raise ValueError("requests_per_hour must be >= 1")
        if self.concurrent is not None and self.concurrent < 1:
            raise ValueError("concurrent must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests_per_min": self.requests_per_min,
            "requests_per_hour": self.requests_per_hour,
            "concurrent": self.concurrent,
        }


# ── Decision ───────────────────────────────────────────────────


@dataclass
class RateLimitDecision:
    """Outcome of a ``RateLimiter.can_call`` check.

    ``allow`` — may the caller proceed right now?
    ``reason`` — short human-readable reason when rejected.
    ``retry_after_s`` — minimum wait, in seconds, until a token is
    expected to be available. ``None`` means "no policy, always
    allowed". Used by the router to choose between "queue and wait"
    vs. "fail over to a sibling adapter".
    """

    allow: bool
    adapter: str
    reason: str = ""
    retry_after_s: float | None = None
    tokens_min: float | None = None
    tokens_hour: float | None = None


# ── Token bucket ───────────────────────────────────────────────


class TokenBucket:
    """Classic token bucket — thread-safe, lock-per-bucket.

    Tokens refill at ``capacity / window_s`` per second up to
    ``capacity``. ``try_acquire(n)`` consumes ``n`` tokens atomically
    if available, otherwise returns ``False`` along with the time
    until the next token lands.

    The bucket holds no knowledge of wall-clock policy — the caller
    decides what ``capacity`` and ``window_s`` mean (per minute, per
    hour, per day). That keeps one class serving every window.
    """

    __slots__ = (
        "capacity", "window_s", "_tokens", "_last_refill",
        "_lock", "_clock",
    )

    def __init__(
        self,
        capacity: int,
        window_s: float,
        *,
        clock=time.monotonic,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if window_s <= 0:
            raise ValueError("window_s must be > 0")
        self.capacity = capacity
        self.window_s = window_s
        self._tokens = float(capacity)
        self._last_refill = clock()
        self._lock = threading.Lock()
        self._clock = clock

    # ── refill math ────────────────────────────────────

    def _refill(self) -> None:
        """Advance the bucket toward full. Must be called under lock."""
        now = self._clock()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        rate = self.capacity / self.window_s  # tokens per second
        self._tokens = min(self.capacity, self._tokens + rate * elapsed)
        self._last_refill = now

    # ── public API ─────────────────────────────────────

    def try_acquire(self, n: int = 1) -> tuple[bool, float]:
        """Consume ``n`` tokens atomically.

        Returns ``(ok, retry_after_s)``. When ``ok`` is ``True`` the
        second value is ``0.0``. When ``ok`` is ``False`` it is the
        estimated seconds until the bucket holds enough tokens for
        this request.
        """
        if n < 1:
            raise ValueError("n must be >= 1")
        with self._lock:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return True, 0.0
            deficit = n - self._tokens
            rate = self.capacity / self.window_s
            wait = deficit / rate if rate > 0 else float("inf")
            return False, wait

    def tokens_available(self) -> float:
        """Read-only peek at the current token count."""
        with self._lock:
            self._refill()
            return self._tokens

    def reset(self) -> None:
        """Test-only — refill to capacity immediately."""
        with self._lock:
            self._tokens = float(self.capacity)
            self._last_refill = self._clock()


# ── Per-adapter cell ───────────────────────────────────────────


@dataclass
class _AdapterCell:
    """Holds the per-window buckets plus an in-flight counter."""
    policy: RateLimit
    minute: TokenBucket | None = None
    hour: TokenBucket | None = None
    in_flight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)


# ── Default catalog ────────────────────────────────────────────


#: Conservative defaults tuned to paid-tier vendor limits circa
#: 2025. Operators override per-adapter via ``RateLimiter(policies=)``.
DEFAULT_POLICIES: dict[str, RateLimit] = {
    # LLM vendors
    "openai":     RateLimit(requests_per_min=500, concurrent=20),
    "anthropic":  RateLimit(requests_per_min=50,  concurrent=10),
    "groq":       RateLimit(requests_per_min=30,  concurrent=10),
    "gemini":     RateLimit(requests_per_min=60,  concurrent=10),
    "mistral":    RateLimit(requests_per_min=60,  concurrent=10),
    "deepseek":   RateLimit(requests_per_min=60,  concurrent=10),
    "openrouter": RateLimit(requests_per_min=200, concurrent=20),

    # Shopify REST — 2 req/s on the standard plan, 4 on Plus. Use 2/s.
    "shopify_products": RateLimit(requests_per_min=120, concurrent=4),
    "shopify_orders":   RateLimit(requests_per_min=120, concurrent=4),
    "shopify_customers":RateLimit(requests_per_min=120, concurrent=4),

    # Email — Postmark 300/s headroom, conservative 600/min.
    "postmark": RateLimit(requests_per_min=600, concurrent=10),
    "sendgrid": RateLimit(requests_per_min=600, concurrent=10),
    "brevo":    RateLimit(requests_per_min=400, concurrent=10),
    "resend":   RateLimit(requests_per_min=600, concurrent=10),

    # Image generation — slower vendors, keep concurrency tight.
    "dalle3":   RateLimit(requests_per_min=50,  concurrent=5),

    # Payment — Stripe 100/s burst, use 500/min safely.
    "stripe":   RateLimit(requests_per_min=500, concurrent=10),
    "paypal":   RateLimit(requests_per_min=300, concurrent=10),
}


# ── Limiter ────────────────────────────────────────────────────


class RateLimiter:
    """Per-adapter rate limiter, thread-safe.

    The limiter composes up to three gates per adapter:
      1. Minute bucket — primary guard against "too fast right now"
      2. Hour bucket — secondary guard against sustained overuse
      3. Concurrent counter — ceiling on simultaneous in-flight calls

    A call is allowed only when every configured gate has capacity.
    Adapters with no policy registered are always allowed — the
    limiter never invents limits, it only enforces declared ones.
    """

    def __init__(
        self,
        policies: dict[str, RateLimit] | None = None,
        *,
        clock=time.monotonic,
    ) -> None:
        self._clock = clock
        self._cells: dict[str, _AdapterCell] = {}
        self._registry_lock = threading.RLock()
        src = policies if policies is not None else DEFAULT_POLICIES
        for name, policy in src.items():
            self.set_policy(name, policy)

    # ── policy management ────────────────────────────────

    def set_policy(self, adapter: str, policy: RateLimit) -> None:
        """Register or replace the policy for ``adapter``."""
        with self._registry_lock:
            cell = _AdapterCell(policy=policy)
            if policy.requests_per_min is not None:
                cell.minute = TokenBucket(
                    capacity=policy.requests_per_min,
                    window_s=60.0,
                    clock=self._clock,
                )
            if policy.requests_per_hour is not None:
                cell.hour = TokenBucket(
                    capacity=policy.requests_per_hour,
                    window_s=3600.0,
                    clock=self._clock,
                )
            self._cells[adapter] = cell

    def get_policy(self, adapter: str) -> RateLimit | None:
        cell = self._cells.get(adapter)
        return cell.policy if cell else None

    def policies(self) -> dict[str, RateLimit]:
        with self._registry_lock:
            return {name: cell.policy for name, cell in self._cells.items()}

    # ── gate ──────────────────────────────────────────────

    def can_call(self, adapter: str, cost: int = 1) -> RateLimitDecision:
        """Atomically reserve ``cost`` tokens in every configured window.

        Adapters without a registered policy always return
        ``allow=True, retry_after_s=None``. If any window is out of
        tokens we roll back the ones we already took so the state
        remains consistent for the next caller.
        """
        cell = self._cells.get(adapter)
        if cell is None:
            return RateLimitDecision(allow=True, adapter=adapter)

        with cell._lock:
            # Concurrency gate is instant — check first.
            if cell.policy.concurrent is not None \
                    and cell.in_flight >= cell.policy.concurrent:
                return RateLimitDecision(
                    allow=False,
                    adapter=adapter,
                    reason=f"concurrent cap {cell.policy.concurrent} reached",
                    retry_after_s=None,
                )

            # Minute bucket.
            min_ok, min_wait = (True, 0.0)
            if cell.minute is not None:
                min_ok, min_wait = cell.minute.try_acquire(cost)
                if not min_ok:
                    return RateLimitDecision(
                        allow=False,
                        adapter=adapter,
                        reason=f"per-minute cap {cell.policy.requests_per_min}",
                        retry_after_s=min_wait,
                        tokens_min=0.0,
                    )

            # Hour bucket — only consume if minute was satisfied.
            hour_ok, hour_wait = (True, 0.0)
            if cell.hour is not None:
                hour_ok, hour_wait = cell.hour.try_acquire(cost)
                if not hour_ok:
                    # Roll back the minute consumption.
                    if cell.minute is not None:
                        with cell.minute._lock:
                            cell.minute._tokens = min(
                                cell.minute.capacity,
                                cell.minute._tokens + cost,
                            )
                    return RateLimitDecision(
                        allow=False,
                        adapter=adapter,
                        reason=f"per-hour cap {cell.policy.requests_per_hour}",
                        retry_after_s=hour_wait,
                        tokens_hour=0.0,
                    )

            # Reserve a concurrency slot.
            cell.in_flight += 1

            tokens_min = cell.minute.tokens_available() if cell.minute else None
            tokens_hour = cell.hour.tokens_available() if cell.hour else None
            return RateLimitDecision(
                allow=True,
                adapter=adapter,
                retry_after_s=0.0,
                tokens_min=tokens_min,
                tokens_hour=tokens_hour,
            )

    def release_slot(self, adapter: str) -> None:
        """Mark an in-flight call as completed.

        The router should call this in a ``finally`` block after
        ``can_call`` returned ``allow=True``. No-op for adapters
        without a policy or with no concurrency cap.
        """
        cell = self._cells.get(adapter)
        if cell is None:
            return
        with cell._lock:
            if cell.in_flight > 0:
                cell.in_flight -= 1

    # ── introspection ─────────────────────────────────────

    def snapshot(self) -> list[dict[str, Any]]:
        """Per-adapter JSON-safe state for the dashboard.

        One row per registered adapter with policy values, current
        tokens in each bucket, and in-flight count. Sorted by adapter
        name for stable output.
        """
        with self._registry_lock:
            rows: list[dict[str, Any]] = []
            for name in sorted(self._cells):
                cell = self._cells[name]
                policy = cell.policy
                tokens_min = cell.minute.tokens_available() if cell.minute else None
                tokens_hour = cell.hour.tokens_available() if cell.hour else None

                # Compute used_pct for the dashboard (0.0-1.0).
                def _pct(avail: float | None, cap: int | None) -> float | None:
                    if avail is None or cap is None or cap == 0:
                        return None
                    return max(0.0, min(1.0, 1.0 - avail / cap))

                rows.append({
                    "adapter": name,
                    "policy": policy.to_dict(),
                    "tokens_min": tokens_min,
                    "tokens_hour": tokens_hour,
                    "in_flight": cell.in_flight,
                    "minute_used_pct": _pct(tokens_min, policy.requests_per_min),
                    "hour_used_pct": _pct(tokens_hour, policy.requests_per_hour),
                    "status": _grade(
                        _pct(tokens_min, policy.requests_per_min),
                        _pct(tokens_hour, policy.requests_per_hour),
                        cell.in_flight, policy.concurrent,
                    ),
                })
            return rows

    def totals(self, rows: list[dict[str, Any]] | None = None) -> dict[str, int]:
        """Rollup ``{"throttled":n,"near":n,"ok":n,"idle":n}``."""
        rows = rows if rows is not None else self.snapshot()
        out = {"throttled": 0, "near": 0, "ok": 0, "idle": 0}
        for r in rows:
            status = r.get("status", "idle")
            out[status] = out.get(status, 0) + 1
        return out

    def reset(self, adapter: str | None = None) -> None:
        """Test helper — refill buckets and clear in-flight counters."""
        with self._registry_lock:
            targets = [adapter] if adapter else list(self._cells)
            for name in targets:
                cell = self._cells.get(name)
                if cell is None:
                    continue
                with cell._lock:
                    if cell.minute is not None:
                        cell.minute.reset()
                    if cell.hour is not None:
                        cell.hour.reset()
                    cell.in_flight = 0


#: Ratio of capacity used that flips "ok" → "near" in the dashboard.
NEAR_RATIO = 0.8


def _grade(
    minute_used: float | None,
    hour_used: float | None,
    in_flight: int,
    concurrent_cap: int | None,
) -> str:
    """Turn raw utilisation into a four-tone traffic light.

    * ``throttled`` — at least one gate is saturated (>=100% used or
      concurrent slots full). The limiter is actively rejecting.
    * ``near``     — within NEAR_RATIO of any configured gate.
    * ``ok``       — policy configured, running below 80% headroom.
    * ``idle``     — no policy configured (the limiter is a no-op).
    """
    # No windows configured → "idle".
    if minute_used is None and hour_used is None and concurrent_cap is None:
        return "idle"

    throttled = False
    near = False

    if minute_used is not None:
        if minute_used >= 1.0:
            throttled = True
        elif minute_used >= NEAR_RATIO:
            near = True

    if hour_used is not None:
        if hour_used >= 1.0:
            throttled = True
        elif hour_used >= NEAR_RATIO:
            near = True

    if concurrent_cap is not None and concurrent_cap > 0:
        c_used = in_flight / concurrent_cap
        if c_used >= 1.0:
            throttled = True
        elif c_used >= NEAR_RATIO:
            near = True

    if throttled:
        return "throttled"
    if near:
        return "near"
    return "ok"


# ── Process-wide singleton ─────────────────────────────────────


_default_limiter: RateLimiter | None = None
_default_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """Return the process-wide limiter singleton.

    Populated with ``DEFAULT_POLICIES`` on first access so every
    adapter in the registry gets a sensible default without any
    bootstrap code. Tests should use ``reset_rate_limiter()`` to
    start from a known state.
    """
    global _default_limiter
    if _default_limiter is None:
        with _default_lock:
            if _default_limiter is None:
                _default_limiter = RateLimiter()
    return _default_limiter


def reset_rate_limiter() -> None:
    """Drop the singleton so the next ``get_rate_limiter()`` rebuilds it."""
    global _default_limiter
    with _default_lock:
        _default_limiter = None
