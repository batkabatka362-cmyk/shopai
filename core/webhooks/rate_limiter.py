"""Per-IP token-bucket rate limiter for the webhook endpoint.

Defence-in-depth on top of HMAC verification (commit 9d1100d):
even with a strong secret an attacker who only sends garbage
can starve CPU on the HMAC compare path. This module caps the
request rate from any single source IP via a simple token-
bucket so abusive callers degrade fast while real Shopify
traffic stays unaffected.

Algorithm: classic token bucket per ``client_ip``.

  * Each bucket holds at most ``burst`` tokens.
  * Tokens refill at ``rate_rpm`` per minute (smoothly — i.e.
    fractional tokens accumulate).
  * ``consume(ip, n=1)`` returns True if tokens were charged,
    False otherwise.
  * Buckets idle for ``idle_evict_s`` (default 1h) are GC'd to
    keep memory bounded; the GC scan runs on every consume()
    so there's no background thread.

Defaults are conservative — Shopify retries with backoff so
60 rpm + burst 30 is plenty for legitimate traffic.

Pure stdlib. Thread-safe via Lock. now_fn dependency-injected
so tests don't sleep.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any


_DEFAULT_RATE_RPM = 60.0
_DEFAULT_BURST = 30
_DEFAULT_IDLE_EVICT_S = 3600.0


@dataclass
class RateLimitDecision:
    allowed: bool
    retry_after_s: float = 0.0
    tokens_remaining: float = 0.0
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "retry_after_s": round(self.retry_after_s, 3),
            "tokens_remaining": round(
                self.tokens_remaining, 3,
            ),
            "reason": self.reason,
        }


@dataclass
class _Bucket:
    tokens: float
    last_refill_ts: float


def _resolved_rate_rpm() -> float:
    raw = os.environ.get(
        "SHOPAI_WEBHOOK_RATE_LIMIT_RPM", "",
    ).strip()
    if not raw:
        return _DEFAULT_RATE_RPM
    try:
        v = float(raw)
        return v if v > 0 else _DEFAULT_RATE_RPM
    except ValueError:
        return _DEFAULT_RATE_RPM


def _resolved_burst() -> int:
    raw = os.environ.get(
        "SHOPAI_WEBHOOK_RATE_LIMIT_BURST", "",
    ).strip()
    if not raw:
        return _DEFAULT_BURST
    try:
        v = int(raw)
        return v if v > 0 else _DEFAULT_BURST
    except ValueError:
        return _DEFAULT_BURST


class WebhookRateLimiter:
    """Per-IP token bucket. Single global instance via
    :func:`get_webhook_rate_limiter`."""

    def __init__(
        self,
        *,
        rate_rpm: float | None = None,
        burst: int | None = None,
        idle_evict_s: float = _DEFAULT_IDLE_EVICT_S,
        now_fn: Any = None,
    ) -> None:
        self._rate_per_s = (
            float(rate_rpm)
            if rate_rpm is not None
            else _resolved_rate_rpm()
        ) / 60.0
        self._burst = float(
            burst if burst is not None
            else _resolved_burst(),
        )
        if self._rate_per_s <= 0:
            raise ValueError("rate_rpm must be > 0")
        if self._burst <= 0:
            raise ValueError("burst must be > 0")
        self._idle_evict_s = float(idle_evict_s)
        self._now_fn = now_fn or time.time
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}
        self._consumed_total = 0
        self._rejected_total = 0

    def consume(
        self, client_ip: str, n: float = 1.0,
    ) -> RateLimitDecision:
        """Try to charge ``n`` tokens for ``client_ip``.

        Returns a :class:`RateLimitDecision` whose
        ``allowed`` field is False on starvation. The
        ``retry_after_s`` hint is the seconds the caller
        should wait before another request — usable as the
        ``Retry-After`` HTTP header.
        """
        if n <= 0:
            return RateLimitDecision(
                allowed=True,
                tokens_remaining=self._burst,
                reason="zero-charge no-op",
            )
        if not client_ip:
            client_ip = "_unknown"
        now = float(self._now_fn())
        with self._lock:
            self._gc_idle(now)
            bucket = self._buckets.get(client_ip)
            if bucket is None:
                bucket = _Bucket(
                    tokens=self._burst,
                    last_refill_ts=now,
                )
                self._buckets[client_ip] = bucket
            else:
                # Refill — fractional, capped at burst.
                elapsed = max(
                    0.0, now - bucket.last_refill_ts,
                )
                bucket.tokens = min(
                    self._burst,
                    bucket.tokens
                    + elapsed * self._rate_per_s,
                )
                bucket.last_refill_ts = now
            if bucket.tokens >= n:
                bucket.tokens -= n
                self._consumed_total += 1
                return RateLimitDecision(
                    allowed=True,
                    tokens_remaining=bucket.tokens,
                )
            deficit = n - bucket.tokens
            retry = deficit / self._rate_per_s
            self._rejected_total += 1
            return RateLimitDecision(
                allowed=False,
                retry_after_s=retry,
                tokens_remaining=bucket.tokens,
                reason=(
                    f"rate limit ({n - bucket.tokens:.2f} "
                    "tokens short)"
                ),
            )

    def _gc_idle(self, now: float) -> None:
        """Drop buckets that haven't been touched for
        ``_idle_evict_s``. Keeps memory bounded under
        churn-y IP sets (e.g. botnets)."""
        if self._idle_evict_s <= 0:
            return
        cutoff = now - self._idle_evict_s
        stale = [
            ip for ip, b in self._buckets.items()
            if b.last_refill_ts < cutoff
        ]
        for ip in stale:
            self._buckets.pop(ip, None)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active_buckets": len(self._buckets),
                "consumed_total": self._consumed_total,
                "rejected_total": self._rejected_total,
                "rate_rpm": round(
                    self._rate_per_s * 60.0, 2,
                ),
                "burst": self._burst,
            }

    def reset(self) -> None:
        """Clear every bucket — used by tests + admin."""
        with self._lock:
            self._buckets.clear()
            self._consumed_total = 0
            self._rejected_total = 0


# ── Singleton ─────────────────────────────────────────────

_SINGLETON: WebhookRateLimiter | None = None
_SINGLETON_LOCK = threading.Lock()


def get_webhook_rate_limiter() -> WebhookRateLimiter:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = WebhookRateLimiter()
    return _SINGLETON


def reset_webhook_rate_limiter_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None
