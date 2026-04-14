"""Router + rate limiter integration — Option U phase 2.

Validates that ``SmartRouter`` honours the attached rate limiter:

* a saturated minute bucket forces the router onto its fallback
* a full concurrency cell forces fallback
* the concurrency slot is released after the adapter call, even on
  a raised exception
* the limiter is exposed via ``router.rate_limiter`` so dashboards
  can snapshot it
* adapters with no policy registered pass through unchanged
"""
from __future__ import annotations

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
    SmartRouter,
    get_registry,
    reset_registry,
)
from core.adapters.rate_limit import RateLimit, RateLimiter


class _StubAdapter(BaseAdapter):
    def __init__(
        self,
        *,
        name: str,
        priority: int = 50,
        raises: Exception | None = None,
    ):
        self.name = name
        self.capabilities = {Capability.CHAT_COMPLETE}
        self.category = AdapterCategory.LLM
        self.priority = priority
        self.cost_per_call = 0.0
        super().__init__()
        self.calls = 0
        self._raises = raises

    def is_configured(self) -> bool:
        return True

    def _execute(self, capability, params):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"text": "ok"},
        )


def _router_with(limiter: RateLimiter, *adapters) -> SmartRouter:
    reset_registry()
    reg = get_registry()
    for a in adapters:
        reg.register(a)
    return SmartRouter(registry=reg, rate_limiter=limiter)


class TestRateGateSkipsSaturated:
    def test_minute_cap_forces_fallback(self):
        primary = _StubAdapter(name="primary", priority=99)
        backup = _StubAdapter(name="backup", priority=50)
        lim = RateLimiter(policies={
            "primary": RateLimit(requests_per_min=1),
        })
        router = _router_with(lim, primary, backup)

        # First call fits in the bucket → primary wins.
        r1 = router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        assert r1.ok and r1.adapter == "primary"
        # Second call is over-capacity → router skips primary.
        r2 = router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        assert r2.ok and r2.adapter == "backup"
        assert primary.calls == 1
        assert backup.calls == 1

    def test_concurrent_cap_forces_fallback(self):
        primary = _StubAdapter(name="primary", priority=99)
        backup = _StubAdapter(name="backup", priority=50)
        lim = RateLimiter(policies={
            "primary": RateLimit(concurrent=1),
        })
        # Pre-reserve the concurrency slot so the router gate is shut.
        assert lim.can_call("primary").allow is True
        router = _router_with(lim, primary, backup)
        r = router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        assert r.ok and r.adapter == "backup"
        assert primary.calls == 0


class TestSlotRelease:
    def test_slot_released_after_success(self):
        primary = _StubAdapter(name="primary", priority=99)
        lim = RateLimiter(policies={
            "primary": RateLimit(concurrent=1),
        })
        router = _router_with(lim, primary)

        router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        # After the call, the slot must be free again so the next
        # call can land on primary rather than being rejected.
        row = next(r for r in lim.snapshot() if r["adapter"] == "primary")
        assert row["in_flight"] == 0

    def test_slot_released_after_exception(self):
        """If the adapter raises and BaseAdapter's wrapper still
        raises upward, the router must release the slot in finally."""
        broken = _StubAdapter(name="broken", raises=RuntimeError("boom"))
        lim = RateLimiter(policies={
            "broken": RateLimit(concurrent=1),
        })
        router = _router_with(lim, broken)

        # BaseAdapter.execute wraps into AdapterResult.failure, so no
        # exception propagates; the slot release should still run.
        router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        row = next(r for r in lim.snapshot() if r["adapter"] == "broken")
        assert row["in_flight"] == 0


class TestPolicyAbsence:
    def test_no_policy_means_always_allowed(self):
        a = _StubAdapter(name="no-policy")
        lim = RateLimiter(policies={})
        router = _router_with(lim, a)
        for _ in range(10):
            r = router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
            assert r.ok
        assert a.calls == 10


class TestAccessor:
    def test_rate_limiter_property(self):
        lim = RateLimiter(policies={})
        router = SmartRouter(registry=get_registry(), rate_limiter=lim)
        assert router.rate_limiter is lim


class TestFallbackExhausted:
    def test_all_throttled_returns_failure(self):
        a = _StubAdapter(name="a", priority=99)
        b = _StubAdapter(name="b", priority=50)
        lim = RateLimiter(policies={
            "a": RateLimit(requests_per_min=1),
            "b": RateLimit(requests_per_min=1),
        })
        router = _router_with(lim, a, b)
        # First call → a.
        router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        # Second call → b.
        router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        # Third call → both throttled, router has no candidates left.
        r = router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        assert not r.ok
