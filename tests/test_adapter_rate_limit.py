"""Rate limiter tests — Option U phase 1.

Covers ``RateLimit`` validation, the ``TokenBucket`` refill math,
the ``RateLimiter`` gate (minute + hour + concurrency composition,
rollback semantics), snapshot grading, and the process-wide
singleton.
"""
from __future__ import annotations

import threading

import pytest

from core.adapters.rate_limit import (
    DEFAULT_POLICIES,
    NEAR_RATIO,
    RateLimit,
    RateLimitDecision,
    RateLimiter,
    TokenBucket,
    get_rate_limiter,
    reset_rate_limiter,
)


class _Clock:
    """Monotonic fake clock — deterministic tests for time-based refill."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


class TestRateLimit:
    def test_requires_positive_fields(self):
        with pytest.raises(ValueError):
            RateLimit(requests_per_min=0)
        with pytest.raises(ValueError):
            RateLimit(requests_per_hour=0)
        with pytest.raises(ValueError):
            RateLimit(concurrent=0)

    def test_all_none_is_valid(self):
        # A policy with nothing set is a valid "no-op" declaration.
        RateLimit()

    def test_to_dict_roundtrip(self):
        r = RateLimit(requests_per_min=10, requests_per_hour=100, concurrent=5)
        assert r.to_dict() == {
            "requests_per_min": 10,
            "requests_per_hour": 100,
            "concurrent": 5,
        }


class TestTokenBucket:
    def test_starts_full(self):
        c = _Clock()
        b = TokenBucket(capacity=10, window_s=60.0, clock=c)
        assert b.tokens_available() == 10.0

    def test_try_acquire_consumes(self):
        c = _Clock()
        b = TokenBucket(capacity=3, window_s=60.0, clock=c)
        ok, wait = b.try_acquire()
        assert ok and wait == 0.0
        assert b.tokens_available() == pytest.approx(2.0)

    def test_rejects_when_empty(self):
        c = _Clock()
        b = TokenBucket(capacity=2, window_s=60.0, clock=c)
        b.try_acquire(2)
        ok, wait = b.try_acquire()
        assert not ok
        # Refill rate is 2/60 tokens/s — 1 token in 30s.
        assert wait == pytest.approx(30.0, rel=1e-3)

    def test_refill_over_time(self):
        c = _Clock()
        b = TokenBucket(capacity=60, window_s=60.0, clock=c)  # 1/s
        b.try_acquire(60)
        c.advance(10.0)
        # Should have earned ~10 tokens back.
        assert b.tokens_available() == pytest.approx(10.0, rel=1e-3)

    def test_capacity_is_ceiling(self):
        c = _Clock()
        b = TokenBucket(capacity=5, window_s=1.0, clock=c)
        c.advance(1000.0)
        assert b.tokens_available() == 5.0

    def test_reset_refills(self):
        c = _Clock()
        b = TokenBucket(capacity=5, window_s=60.0, clock=c)
        b.try_acquire(5)
        assert b.tokens_available() == pytest.approx(0.0)
        b.reset()
        assert b.tokens_available() == 5.0

    def test_validation(self):
        with pytest.raises(ValueError):
            TokenBucket(capacity=0, window_s=60.0)
        with pytest.raises(ValueError):
            TokenBucket(capacity=5, window_s=0)


class TestRateLimiterBasics:
    def test_unknown_adapter_always_allowed(self):
        lim = RateLimiter(policies={})
        d = lim.can_call("ghost")
        assert d.allow is True
        assert d.retry_after_s is None

    def test_minute_bucket_blocks_after_saturation(self):
        c = _Clock()
        lim = RateLimiter(
            policies={"x": RateLimit(requests_per_min=2)}, clock=c,
        )
        assert lim.can_call("x").allow is True
        assert lim.can_call("x").allow is True
        d = lim.can_call("x")
        assert d.allow is False
        assert "per-minute" in d.reason
        assert d.retry_after_s and d.retry_after_s > 0

    def test_minute_bucket_refills(self):
        c = _Clock()
        lim = RateLimiter(
            policies={"x": RateLimit(requests_per_min=60)}, clock=c,
        )
        for _ in range(60):
            assert lim.can_call("x").allow
        assert lim.can_call("x").allow is False
        c.advance(1.0)  # 1 token refilled (60/60 = 1/s)
        assert lim.can_call("x").allow is True


class TestRateLimiterHour:
    def test_hour_gate_blocks_after_saturation(self):
        c = _Clock()
        lim = RateLimiter(
            policies={"y": RateLimit(
                requests_per_min=10, requests_per_hour=5,
            )},
            clock=c,
        )
        for _ in range(5):
            assert lim.can_call("y").allow
        d = lim.can_call("y")
        assert d.allow is False
        assert "per-hour" in d.reason

    def test_hour_rejection_rolls_back_minute_tokens(self):
        """If the hour gate trips, the minute gate must NOT have
        consumed a token — otherwise a slow hourly burst would also
        starve the per-minute window forever."""
        c = _Clock()
        lim = RateLimiter(
            policies={"y": RateLimit(
                requests_per_min=100, requests_per_hour=1,
            )},
            clock=c,
        )
        # First call burns the only hourly token.
        assert lim.can_call("y").allow is True
        # Second call fails on hour gate.
        d = lim.can_call("y")
        assert d.allow is False
        assert "per-hour" in d.reason
        # Minute bucket should still show 99 available, not 98.
        row = next(r for r in lim.snapshot() if r["adapter"] == "y")
        # tokens_min should be close to 99 (one consumed on the first
        # allowed call, the rolled-back attempt returned its token).
        assert row["tokens_min"] == pytest.approx(99.0, abs=0.01)


class TestConcurrency:
    def test_concurrent_cap_enforced(self):
        lim = RateLimiter(policies={"z": RateLimit(concurrent=2)})
        assert lim.can_call("z").allow is True
        assert lim.can_call("z").allow is True
        d = lim.can_call("z")
        assert d.allow is False
        assert "concurrent" in d.reason

    def test_release_slot_frees_capacity(self):
        lim = RateLimiter(policies={"z": RateLimit(concurrent=1)})
        assert lim.can_call("z").allow is True
        assert lim.can_call("z").allow is False
        lim.release_slot("z")
        assert lim.can_call("z").allow is True

    def test_release_noop_without_policy(self):
        lim = RateLimiter(policies={})
        lim.release_slot("ghost")  # must not raise

    def test_release_does_not_go_negative(self):
        lim = RateLimiter(policies={"z": RateLimit(concurrent=2)})
        lim.release_slot("z")
        lim.release_slot("z")  # was 0 already
        row = next(r for r in lim.snapshot() if r["adapter"] == "z")
        assert row["in_flight"] == 0


class TestSnapshot:
    def test_snapshot_reports_policy_and_usage(self):
        c = _Clock()
        lim = RateLimiter(
            policies={"openai": RateLimit(
                requests_per_min=10, concurrent=2,
            )},
            clock=c,
        )
        lim.can_call("openai")
        lim.can_call("openai")
        rows = lim.snapshot()
        assert len(rows) == 1
        row = rows[0]
        assert row["adapter"] == "openai"
        assert row["in_flight"] == 2
        assert row["tokens_min"] == pytest.approx(8.0)
        assert row["minute_used_pct"] == pytest.approx(0.2, abs=1e-3)

    def test_grading_ok_near_throttled(self):
        c = _Clock()
        lim = RateLimiter(
            policies={"x": RateLimit(requests_per_min=10)}, clock=c,
        )
        row = next(r for r in lim.snapshot() if r["adapter"] == "x")
        assert row["status"] == "ok"
        # Burn to near the boundary (>=80%).
        for _ in range(8):
            lim.can_call("x")
        row = next(r for r in lim.snapshot() if r["adapter"] == "x")
        assert row["status"] == "near"
        for _ in range(2):
            lim.can_call("x")
        row = next(r for r in lim.snapshot() if r["adapter"] == "x")
        assert row["status"] == "throttled"

    def test_idle_grade_for_empty_policy(self):
        lim = RateLimiter(policies={"empty": RateLimit()})
        row = next(r for r in lim.snapshot() if r["adapter"] == "empty")
        assert row["status"] == "idle"

    def test_totals_rollup(self):
        c = _Clock()
        lim = RateLimiter(
            policies={
                "a": RateLimit(requests_per_min=10),
                "b": RateLimit(requests_per_min=10),
                "c": RateLimit(),
            },
            clock=c,
        )
        for _ in range(10):
            lim.can_call("a")
        for _ in range(8):
            lim.can_call("b")
        totals = lim.totals()
        assert totals["throttled"] == 1
        assert totals["near"] == 1
        assert totals["idle"] == 1


class TestPolicyManagement:
    def test_set_policy_replaces(self):
        lim = RateLimiter(policies={"x": RateLimit(requests_per_min=1)})
        for _ in range(1):
            lim.can_call("x")
        assert lim.can_call("x").allow is False
        # Replace with a larger policy — new buckets are fresh.
        lim.set_policy("x", RateLimit(requests_per_min=10))
        assert lim.can_call("x").allow is True

    def test_get_policy_returns_registered(self):
        p = RateLimit(requests_per_min=5)
        lim = RateLimiter(policies={"x": p})
        assert lim.get_policy("x") == p
        assert lim.get_policy("ghost") is None

    def test_policies_returns_snapshot_copy(self):
        lim = RateLimiter(policies={"x": RateLimit(requests_per_min=5)})
        pols = lim.policies()
        pols["y"] = RateLimit(requests_per_min=99)
        assert "y" not in lim.policies()


class TestDefaultCatalog:
    def test_common_vendors_covered(self):
        assert "openai" in DEFAULT_POLICIES
        assert "anthropic" in DEFAULT_POLICIES
        assert "stripe" in DEFAULT_POLICIES
        assert "postmark" in DEFAULT_POLICIES

    def test_every_default_is_valid(self):
        # Validates the catalog itself — a typo like concurrent=0
        # would fail RateLimit.__post_init__, so round-tripping it
        # here acts as a compile-time check on the module constant.
        for name, policy in DEFAULT_POLICIES.items():
            assert isinstance(policy, RateLimit)
            assert policy.to_dict()["concurrent"] is None or policy.concurrent > 0


class TestSingleton:
    def test_get_returns_same_instance(self):
        a = get_rate_limiter()
        b = get_rate_limiter()
        assert a is b

    def test_reset_drops_singleton(self):
        a = get_rate_limiter()
        reset_rate_limiter()
        b = get_rate_limiter()
        assert a is not b

    def test_default_policies_loaded(self):
        lim = get_rate_limiter()
        # openai is in DEFAULT_POLICIES; should be registered.
        assert lim.get_policy("openai") is not None


class TestThreadSafety:
    def test_concurrent_cap_holds_under_threads(self):
        """Stress test: 20 threads racing for 5 slots should see
        exactly 5 `allow=True` decisions when none release."""
        lim = RateLimiter(policies={"x": RateLimit(concurrent=5)})
        results: list[bool] = []
        lock = threading.Lock()

        def worker():
            d = lim.can_call("x")
            with lock:
                results.append(d.allow)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(1 for r in results if r) == 5


class TestNearRatioConstant:
    def test_near_ratio_is_eighty_percent(self):
        """Documented contract — the dashboard legend mirrors this.
        If we change the ratio, update the dashboard copy too."""
        assert NEAR_RATIO == 0.8
