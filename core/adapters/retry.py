"""Adapter retry policy + circuit breaker — Option R.

The router already falls back across adapters on failure, but it
gives up on the primary after a single attempt. Real-world vendor
APIs frequently return transient errors (HTTP 429, 502, connection
reset) that succeed on a quick retry — routing straight to a
fallback costs more, returns worse quality, and burns the fallback's
quota for no reason.

This module supplies two small reusable primitives:

* ``RetryPolicy`` — exponential backoff with jitter, bounded by
  ``max_attempts`` and ``giveup_after_s``. Classifies each
  ``AdapterError`` as retryable (``AdapterRateLimited``,
  ``AdapterUnavailable``, ``AdapterTimeout``) or permanent
  (``AdapterAuthError``, ``AdapterValidationError``,
  ``AdapterQuotaExhausted``, ``AdapterNotConfigured``).

* ``CircuitBreaker`` — per-adapter consecutive-failure counter.
  After ``fail_threshold`` consecutive failures the breaker is
  ``open`` and the router skips the adapter for
  ``reset_after_s`` seconds before a single ``half_open`` probe.

Both are pure, thread-safe, and carry no framework dependencies —
they can be unit-tested in isolation and composed into the router
with a thin wrapper.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from core.adapters.errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterQuotaExhausted,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

logger = logging.getLogger(__name__)


# ── Retry policy ─────────────────────────────────────────────────


#: Error classes that represent transient failure — the same call
#: has a decent chance of succeeding a moment later. Everything
#: else is treated as permanent and fails fast.
_RETRYABLE: tuple[type[AdapterError], ...] = (
    AdapterRateLimited,
    AdapterUnavailable,
    AdapterTimeout,
)


#: Error classes that MUST never retry — either a caller bug
#: (validation), an auth failure (key rotation needed), or a
#: budget exhaustion that retrying just makes more expensive.
_PERMANENT: tuple[type[AdapterError], ...] = (
    AdapterAuthError,
    AdapterValidationError,
    AdapterQuotaExhausted,
    AdapterNotConfigured,
)


def is_retryable(error: AdapterError | None) -> bool:
    """Return True iff ``error`` is one of the transient classes.

    ``None`` is considered non-retryable — the caller already
    succeeded. Unknown subclasses default to non-retryable so a
    mis-classified error can't turn into a retry storm.
    """
    if error is None:
        return False
    if isinstance(error, _PERMANENT):
        return False
    if isinstance(error, _RETRYABLE):
        return True
    return False


@dataclass
class RetryPolicy:
    """Exponential backoff policy for adapter calls.

    Every field has a default tuned for production LLM APIs — the
    caller can override any subset. Pass ``max_attempts=1`` to
    effectively disable retries while still keeping the same
    calling convention.
    """

    #: Total attempts including the first call. ``max_attempts=3``
    #: means one original + up to two retries.
    max_attempts: int = 3

    #: First backoff wait, in seconds. Subsequent waits are
    #: ``base_s * multiplier ** (attempt_no - 1)``.
    base_s: float = 0.5

    #: Backoff multiplier. 2.0 doubles the wait each time.
    multiplier: float = 2.0

    #: Cap on any single backoff wait, in seconds.
    max_backoff_s: float = 10.0

    #: Wall-clock budget across ALL attempts (including retries).
    #: Once this is exceeded we stop retrying even if
    #: ``max_attempts`` remain.
    giveup_after_s: float = 15.0

    #: ``±jitter_pct`` randomisation applied to each backoff so
    #: retries from multiple callers don't stampede in lock-step.
    jitter_pct: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_s < 0:
            raise ValueError("base_s must be >= 0")
        if self.multiplier < 1.0:
            raise ValueError("multiplier must be >= 1.0")
        if not 0 <= self.jitter_pct <= 1.0:
            raise ValueError("jitter_pct must be within [0, 1]")

    # ── backoff math ────────────────────────────────────────

    def backoff_for(self, attempt_no: int, retry_after: float | None = None) -> float:
        """Return the wait (seconds) before attempt #``attempt_no``.

        ``attempt_no`` is 1-based: ``backoff_for(1)`` returns the wait
        before the FIRST retry (i.e. after the original call failed).
        A vendor-supplied ``retry_after`` (from HTTP 429) takes
        precedence over the policy's computed value.
        """
        if attempt_no < 1:
            return 0.0
        if retry_after is not None and retry_after > 0:
            return min(float(retry_after), self.max_backoff_s)
        raw = self.base_s * (self.multiplier ** (attempt_no - 1))
        raw = min(raw, self.max_backoff_s)
        if self.jitter_pct > 0:
            spread = raw * self.jitter_pct
            raw = raw + random.uniform(-spread, spread)
        return max(0.0, raw)

    # ── executor ───────────────────────────────────────────

    def run(
        self,
        call: Callable[[], "_ResultLike"],
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> "RetryOutcome":
        """Invoke ``call`` with retries.

        ``call`` must return an object with an ``ok`` bool attribute
        and (on failure) an ``error`` attribute whose value is an
        ``AdapterError`` instance — i.e. the ``AdapterResult``
        contract. We return a ``RetryOutcome`` carrying the final
        result plus per-attempt telemetry.
        """
        started = clock()
        attempts: list[_AttemptRecord] = []

        last_result: _ResultLike | None = None
        for i in range(1, self.max_attempts + 1):
            elapsed_before = clock() - started
            if i > 1 and elapsed_before >= self.giveup_after_s:
                logger.debug(
                    "retry budget exhausted (%.2fs >= %.2fs), giving up",
                    elapsed_before, self.giveup_after_s,
                )
                break

            attempt_start = clock()
            try:
                result = call()
            except AdapterError as exc:
                # Callers sometimes raise instead of returning a
                # failure envelope — honour that path too.
                result = _FailShim(error=exc)
            attempt_ms = (clock() - attempt_start) * 1000.0
            last_result = result

            err = getattr(result, "error", None)
            attempts.append(_AttemptRecord(
                attempt_no=i,
                ok=bool(getattr(result, "ok", False)),
                error_class=type(err).__name__ if err else "",
                latency_ms=attempt_ms,
            ))

            if getattr(result, "ok", False):
                return RetryOutcome(
                    result=result,
                    attempts=attempts,
                    retried=i > 1,
                    gave_up=False,
                )
            if not is_retryable(err):
                return RetryOutcome(
                    result=result,
                    attempts=attempts,
                    retried=i > 1,
                    gave_up=False,
                )
            if i == self.max_attempts:
                break  # spent our budget

            # Honour vendor's Retry-After when present.
            retry_after = getattr(err, "retry_after", None) \
                if err is not None else None
            wait = self.backoff_for(i, retry_after=retry_after)
            # Respect the wall budget — no point sleeping past it.
            remaining = self.giveup_after_s - (clock() - started)
            if wait >= remaining:
                break
            if wait > 0:
                sleep(wait)

        return RetryOutcome(
            result=last_result,
            attempts=attempts,
            retried=len(attempts) > 1,
            gave_up=True,
        )


# ── Outcome records ──────────────────────────────────────────────


@dataclass
class _AttemptRecord:
    """Per-attempt telemetry surfaced on ``RetryOutcome``."""
    attempt_no: int
    ok: bool
    error_class: str
    latency_ms: float


@dataclass
class RetryOutcome:
    """Full story of a retry-wrapped call.

    * ``result`` — the final ``AdapterResult`` (success or last failure)
    * ``attempts`` — one record per call
    * ``retried`` — True if more than one attempt ran
    * ``gave_up`` — True if we exited without seeing ``ok=True``
    """
    result: "_ResultLike | None"
    attempts: list[_AttemptRecord]
    retried: bool
    gave_up: bool

    @property
    def attempts_count(self) -> int:
        return len(self.attempts)


# Structural type alias — anything with ``ok`` and ``error`` fits.
class _ResultLike:  # pragma: no cover — protocol-only marker
    ok: bool
    error: AdapterError | None


@dataclass
class _FailShim:
    """Wraps a raised AdapterError as a result-shaped object."""
    error: AdapterError
    ok: bool = False


# ── Circuit breaker ──────────────────────────────────────────────


@dataclass
class CircuitBreaker:
    """Per-adapter consecutive-failure breaker.

    States:
      * ``closed``    — normal traffic flows
      * ``open``      — every call returns immediately, no adapter hit
      * ``half_open`` — single probe call allowed; success closes,
                        failure reopens the breaker for another window

    The breaker is **opt-in** — callers explicitly ``before_call``
    (which may raise to signal "skip this adapter") and
    ``record_success`` / ``record_failure`` after the call. Keeping
    this decoupled from the policy object means one breaker per
    adapter with a shared policy is trivially composable.
    """

    #: Consecutive failures that flip ``closed`` → ``open``.
    fail_threshold: int = 5

    #: How long the breaker stays ``open`` before a half-open probe.
    reset_after_s: float = 30.0

    #: Ignored by the breaker itself — surfaced in snapshots so
    #: dashboards can describe the policy to operators.
    name: str = ""

    _state: str = field(default="closed", init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _trips: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    # ── state queries ─────────────────────────────────────

    @property
    def state(self) -> str:
        # Read through ``_refresh`` so ``open`` that has aged past
        # ``reset_after_s`` is automatically promoted to ``half_open``
        # without the caller having to poke the breaker first.
        with self._lock:
            self._maybe_half_open(time.monotonic())
            return self._state

    def allow(self, now: float | None = None) -> bool:
        """Return True if the caller may run the wrapped call."""
        with self._lock:
            self._maybe_half_open(now if now is not None else time.monotonic())
            return self._state != "open"

    def snapshot(self) -> dict:
        """Return a JSON-safe view of the breaker for telemetry."""
        with self._lock:
            self._maybe_half_open(time.monotonic())
            return {
                "name": self.name,
                "state": self._state,
                "consecutive_failures": self._consecutive_failures,
                "trips": self._trips,
                "fail_threshold": self.fail_threshold,
                "reset_after_s": self.reset_after_s,
                "opened_at": self._opened_at,
            }

    # ── state transitions ────────────────────────────────

    def record_success(self) -> None:
        """Clear the failure counter and close the breaker."""
        with self._lock:
            self._consecutive_failures = 0
            if self._state in ("open", "half_open"):
                logger.info(
                    "circuit %r recovered: closing breaker",
                    self.name or "<unnamed>",
                )
            self._state = "closed"
            self._opened_at = 0.0

    def record_failure(self) -> None:
        """Bump the counter; trip if threshold hit."""
        with self._lock:
            self._consecutive_failures += 1
            if self._state == "half_open":
                # Probe failed → reopen for another window.
                self._state = "open"
                self._opened_at = time.monotonic()
                self._trips += 1
                logger.warning(
                    "circuit %r half-open probe failed: reopening",
                    self.name or "<unnamed>",
                )
                return
            if self._consecutive_failures >= self.fail_threshold \
                    and self._state == "closed":
                self._state = "open"
                self._opened_at = time.monotonic()
                self._trips += 1
                logger.warning(
                    "circuit %r tripped after %d consecutive failures",
                    self.name or "<unnamed>",
                    self._consecutive_failures,
                )

    # ── private ──────────────────────────────────────────

    def _maybe_half_open(self, now: float) -> None:
        """Promote ``open`` → ``half_open`` once the cool-down has passed.

        Must be called with ``_lock`` held.
        """
        if self._state != "open":
            return
        if now - self._opened_at >= self.reset_after_s:
            self._state = "half_open"
            logger.info(
                "circuit %r cool-down passed: half-open probe allowed",
                self.name or "<unnamed>",
            )


# ── Telemetry registry ──────────────────────────────────────────


class RetryTelemetry:
    """Process-wide aggregator so dashboards have something to read.

    Counts are bucketed per adapter and per outcome class. No TTL —
    these are monotonic counters, analogous to Prometheus. The
    dashboard reads via ``snapshot()`` which is a stable JSON dict.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._per_adapter: dict[str, dict[str, int]] = {}
        self._total_retries = 0
        self._total_giveups = 0
        self._total_calls = 0

    def record(
        self,
        adapter: str,
        outcome: RetryOutcome,
    ) -> None:
        with self._lock:
            row = self._per_adapter.setdefault(adapter, {
                "calls": 0, "retries": 0, "giveups": 0,
                "attempts": 0, "successes": 0,
            })
            row["calls"] += 1
            row["attempts"] += outcome.attempts_count
            if outcome.retried:
                row["retries"] += 1
                self._total_retries += 1
            if outcome.gave_up:
                row["giveups"] += 1
                self._total_giveups += 1
            if outcome.result and getattr(outcome.result, "ok", False):
                row["successes"] += 1
            self._total_calls += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_calls": self._total_calls,
                "total_retries": self._total_retries,
                "total_giveups": self._total_giveups,
                "per_adapter": {
                    k: dict(v) for k, v in self._per_adapter.items()
                },
            }

    def reset(self) -> None:
        """Test-only — wipes every counter."""
        with self._lock:
            self._per_adapter.clear()
            self._total_retries = 0
            self._total_giveups = 0
            self._total_calls = 0


_default_telemetry: RetryTelemetry | None = None
_default_lock = threading.Lock()


def get_retry_telemetry() -> RetryTelemetry:
    """Return the process-wide telemetry singleton."""
    global _default_telemetry
    if _default_telemetry is None:
        with _default_lock:
            if _default_telemetry is None:
                _default_telemetry = RetryTelemetry()
    return _default_telemetry
