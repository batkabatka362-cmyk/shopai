"""Adapter retry policy + circuit breaker — Option R.

Unit-tests the primitives in ``core.adapters.retry``:

* ``is_retryable`` — error-class classifier
* ``RetryPolicy.backoff_for`` — math + jitter bounds + Retry-After
* ``RetryPolicy.run`` — attempt budgeting, wall-clock budget,
  early-bail on permanent errors, success short-circuits retry
* ``CircuitBreaker`` — state machine (closed → open → half_open →
  closed/open), trip threshold, cool-down, concurrent-safety
* ``RetryTelemetry`` — monotonic counters, per-adapter rollups,
  reset semantics
"""
from __future__ import annotations

import random

import pytest

from core.adapters.errors import (
    AdapterAuthError,
    AdapterNotConfigured,
    AdapterQuotaExhausted,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)
from core.adapters.retry import (
    CircuitBreaker,
    RetryOutcome,
    RetryPolicy,
    RetryTelemetry,
    _FailShim,
    get_retry_telemetry,
    is_retryable,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _Result:
    """Minimal AdapterResult-shaped stand-in."""
    def __init__(self, ok: bool, error=None):
        self.ok = ok
        self.error = error


def _make_caller(outcomes):
    """Return a closure that yields each outcome in sequence."""
    iterator = iter(outcomes)

    def _call():
        try:
            return next(iterator)
        except StopIteration:  # pragma: no cover — test bug
            raise AssertionError("caller invoked more times than planned")
    return _call


class _FakeClock:
    def __init__(self, start=0.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class _RecordingSleep:
    def __init__(self, clock=None):
        self.calls = []
        self.clock = clock

    def __call__(self, s):
        self.calls.append(s)
        if self.clock is not None:
            self.clock.advance(s)


# ---------------------------------------------------------------------------
# is_retryable
# ---------------------------------------------------------------------------


class TestIsRetryable:
    def test_rate_limited_retryable(self):
        assert is_retryable(AdapterRateLimited("x")) is True

    def test_unavailable_retryable(self):
        assert is_retryable(AdapterUnavailable("x")) is True

    def test_timeout_retryable(self):
        assert is_retryable(AdapterTimeout("x")) is True

    def test_validation_permanent(self):
        assert is_retryable(AdapterValidationError("x")) is False

    def test_auth_permanent(self):
        assert is_retryable(AdapterAuthError("x")) is False

    def test_quota_permanent(self):
        assert is_retryable(AdapterQuotaExhausted("x")) is False

    def test_not_configured_permanent(self):
        assert is_retryable(AdapterNotConfigured("x")) is False

    def test_none_permanent(self):
        assert is_retryable(None) is False


# ---------------------------------------------------------------------------
# RetryPolicy — construction + backoff math
# ---------------------------------------------------------------------------


class TestRetryPolicyConfig:
    def test_defaults_sane(self):
        p = RetryPolicy()
        assert p.max_attempts == 3
        assert p.base_s == 0.5
        assert p.multiplier == 2.0
        assert p.max_backoff_s == 10.0
        assert p.giveup_after_s == 15.0

    def test_rejects_zero_attempts(self):
        with pytest.raises(ValueError):
            RetryPolicy(max_attempts=0)

    def test_rejects_negative_base(self):
        with pytest.raises(ValueError):
            RetryPolicy(base_s=-1.0)

    def test_rejects_bad_multiplier(self):
        with pytest.raises(ValueError):
            RetryPolicy(multiplier=0.5)

    def test_rejects_bad_jitter(self):
        with pytest.raises(ValueError):
            RetryPolicy(jitter_pct=1.5)


class TestBackoffMath:
    def test_first_retry_uses_base(self):
        p = RetryPolicy(base_s=1.0, multiplier=2.0, jitter_pct=0.0)
        assert p.backoff_for(1) == 1.0

    def test_exponential_growth(self):
        p = RetryPolicy(base_s=1.0, multiplier=2.0, jitter_pct=0.0)
        assert p.backoff_for(2) == 2.0
        assert p.backoff_for(3) == 4.0

    def test_capped_at_max(self):
        p = RetryPolicy(base_s=1.0, multiplier=10.0,
                        max_backoff_s=5.0, jitter_pct=0.0)
        assert p.backoff_for(5) == 5.0

    def test_retry_after_overrides(self):
        p = RetryPolicy(base_s=0.1, jitter_pct=0.0)
        assert p.backoff_for(1, retry_after=3.0) == 3.0

    def test_retry_after_capped_by_max(self):
        p = RetryPolicy(max_backoff_s=2.0, jitter_pct=0.0)
        assert p.backoff_for(1, retry_after=100.0) == 2.0

    def test_jitter_stays_in_bounds(self):
        p = RetryPolicy(base_s=1.0, multiplier=1.0, jitter_pct=0.5)
        # Sample a few times; every sample must be within ±50% of 1.0.
        for _ in range(50):
            w = p.backoff_for(1)
            assert 0.5 <= w <= 1.5

    def test_jitter_zero_deterministic(self):
        p = RetryPolicy(base_s=1.0, jitter_pct=0.0)
        assert p.backoff_for(1) == p.backoff_for(1)

    def test_zero_attempt_returns_zero(self):
        p = RetryPolicy()
        assert p.backoff_for(0) == 0.0


# ---------------------------------------------------------------------------
# RetryPolicy.run
# ---------------------------------------------------------------------------


class TestRetryRun:
    def test_success_on_first_try(self):
        p = RetryPolicy(max_attempts=3)
        sleep = _RecordingSleep()
        ok = _Result(ok=True)
        out = p.run(_make_caller([ok]), sleep=sleep)
        assert out.result is ok
        assert out.retried is False
        assert out.gave_up is False
        assert out.attempts_count == 1
        assert sleep.calls == []  # no backoff happened

    def test_retries_on_transient(self):
        p = RetryPolicy(max_attempts=3, base_s=0.0, jitter_pct=0.0)
        sleep = _RecordingSleep()
        bad = _Result(ok=False, error=AdapterTimeout("vendor"))
        good = _Result(ok=True)
        out = p.run(_make_caller([bad, bad, good]), sleep=sleep)
        assert out.result is good
        assert out.retried is True
        assert out.gave_up is False
        assert out.attempts_count == 3

    def test_no_retry_on_permanent_error(self):
        p = RetryPolicy(max_attempts=5, base_s=0.0)
        sleep = _RecordingSleep()
        bad = _Result(ok=False, error=AdapterValidationError("v"))
        out = p.run(_make_caller([bad]), sleep=sleep)
        assert out.gave_up is False   # not a giveup — we never wanted to retry
        assert out.retried is False
        assert out.attempts_count == 1
        assert sleep.calls == []

    def test_max_attempts_respected(self):
        p = RetryPolicy(max_attempts=2, base_s=0.0, jitter_pct=0.0)
        sleep = _RecordingSleep()
        bad = _Result(ok=False, error=AdapterUnavailable("v"))
        out = p.run(_make_caller([bad, bad]), sleep=sleep)
        assert out.gave_up is True
        assert out.attempts_count == 2

    def test_wall_clock_budget_halts_retries(self):
        clock = _FakeClock()
        sleep = _RecordingSleep(clock=clock)
        # base_s=10 and budget=5 — after the first failure the next
        # backoff (10s) would exceed the budget, so we bail out.
        p = RetryPolicy(max_attempts=5, base_s=10.0, jitter_pct=0.0,
                        giveup_after_s=5.0, max_backoff_s=10.0)
        bad = _Result(ok=False, error=AdapterTimeout("v"))
        out = p.run(_make_caller([bad]), sleep=sleep, clock=clock)
        assert out.gave_up is True
        assert out.attempts_count == 1
        assert sleep.calls == []  # never slept

    def test_retry_after_from_vendor_used(self):
        clock = _FakeClock()
        sleep = _RecordingSleep(clock=clock)
        p = RetryPolicy(max_attempts=2, base_s=0.0, jitter_pct=0.0,
                        max_backoff_s=60.0)
        bad = _Result(ok=False, error=AdapterRateLimited("v", retry_after=2.5))
        good = _Result(ok=True)
        out = p.run(_make_caller([bad, good]), sleep=sleep, clock=clock)
        assert out.result is good
        # Vendor Retry-After=2.5s must be honoured.
        assert sleep.calls == [2.5]

    def test_raised_error_caught_and_classified(self):
        """A call that raises AdapterError is treated like a failure."""
        p = RetryPolicy(max_attempts=2, base_s=0.0, jitter_pct=0.0)

        iter_n = [0]

        def flaky():
            iter_n[0] += 1
            if iter_n[0] == 1:
                raise AdapterTimeout("v")
            return _Result(ok=True)

        sleep = _RecordingSleep()
        out = p.run(flaky, sleep=sleep)
        assert out.result.ok is True
        assert out.attempts_count == 2

    def test_max_attempts_one_disables_retry(self):
        p = RetryPolicy(max_attempts=1)
        bad = _Result(ok=False, error=AdapterTimeout("v"))
        sleep = _RecordingSleep()
        out = p.run(_make_caller([bad]), sleep=sleep)
        assert out.attempts_count == 1
        assert sleep.calls == []


class TestFailShim:
    def test_ok_false_by_default(self):
        shim = _FailShim(error=AdapterTimeout("x"))
        assert shim.ok is False
        assert shim.error.adapter == "x"


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_starts_closed(self):
        br = CircuitBreaker()
        assert br.state == "closed"
        assert br.allow() is True

    def test_trips_at_threshold(self):
        br = CircuitBreaker(fail_threshold=3)
        for _ in range(3):
            br.record_failure()
        assert br.state == "open"
        assert br.allow() is False

    def test_success_resets_counter(self):
        br = CircuitBreaker(fail_threshold=3)
        br.record_failure()
        br.record_failure()
        br.record_success()
        br.record_failure()  # counter was reset; not at threshold yet
        assert br.state == "closed"

    def test_cooldown_promotes_to_half_open(self):
        br = CircuitBreaker(fail_threshold=1, reset_after_s=0.01)
        br.record_failure()
        assert br.state == "open"

        import time
        time.sleep(0.02)
        # Any state query after cool-down promotes to half_open.
        assert br.state == "half_open"
        assert br.allow() is True

    def test_half_open_failure_reopens(self):
        br = CircuitBreaker(fail_threshold=1, reset_after_s=0.01)
        br.record_failure()
        import time
        time.sleep(0.02)
        assert br.state == "half_open"
        br.record_failure()
        assert br.state == "open"

    def test_half_open_success_closes(self):
        br = CircuitBreaker(fail_threshold=1, reset_after_s=0.01)
        br.record_failure()
        import time
        time.sleep(0.02)
        _ = br.state  # force half-open promotion
        br.record_success()
        assert br.state == "closed"

    def test_trip_count_monotonic(self):
        br = CircuitBreaker(fail_threshold=2, reset_after_s=0.01)
        br.record_failure(); br.record_failure()   # trip 1
        import time
        time.sleep(0.02)
        _ = br.state  # half-open
        br.record_failure()  # reopens → trip 2
        snap = br.snapshot()
        assert snap["trips"] == 2

    def test_snapshot_shape(self):
        br = CircuitBreaker(name="demo", fail_threshold=4, reset_after_s=10.0)
        snap = br.snapshot()
        assert snap["name"] == "demo"
        assert snap["state"] == "closed"
        assert snap["fail_threshold"] == 4
        assert snap["reset_after_s"] == 10.0
        assert snap["trips"] == 0


# ---------------------------------------------------------------------------
# RetryTelemetry
# ---------------------------------------------------------------------------


class TestTelemetry:
    def test_records_success(self):
        t = RetryTelemetry()
        outcome = RetryOutcome(
            result=_Result(ok=True), attempts=[],
            retried=False, gave_up=False,
        )
        outcome.attempts = [type("A", (), {"attempt_no": 1, "ok": True,
                                            "error_class": "",
                                            "latency_ms": 5.0})()]
        t.record("openai", outcome)
        snap = t.snapshot()
        assert snap["total_calls"] == 1
        assert snap["total_retries"] == 0
        assert snap["per_adapter"]["openai"]["successes"] == 1

    def test_records_retries_and_giveups(self):
        t = RetryTelemetry()
        # Retried + gave up.
        outcome = RetryOutcome(
            result=_Result(ok=False, error=AdapterTimeout("v")),
            attempts=[],
            retried=True, gave_up=True,
        )
        t.record("anthropic", outcome)
        snap = t.snapshot()
        assert snap["total_retries"] == 1
        assert snap["total_giveups"] == 1
        assert snap["per_adapter"]["anthropic"]["giveups"] == 1

    def test_reset_wipes(self):
        t = RetryTelemetry()
        t.record("x", RetryOutcome(result=_Result(ok=True),
                                   attempts=[], retried=False, gave_up=False))
        t.reset()
        snap = t.snapshot()
        assert snap["total_calls"] == 0
        assert snap["per_adapter"] == {}

    def test_singleton_is_stable(self):
        a = get_retry_telemetry()
        b = get_retry_telemetry()
        assert a is b
