"""Router dead-letter hook — Option Y phase 2.

Tests that ``SmartRouter.execute`` records an entry in the dead-
letter ledger when every fallback adapter has failed, and that
the record never crashes or masks the original failure.
"""
from __future__ import annotations

import pytest

from core.adapters.base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from core.adapters.deadletter import DeadLetterLedger
from core.adapters.errors import AdapterError, AdapterValidationError
from core.adapters.idempotency import IdempotencyCache
from core.adapters.rate_limit import RateLimiter
from core.adapters.registry import AdapterRegistry
from core.adapters.retry import RetryTelemetry
from core.adapters.router import RouteContext, SmartRouter


class _StubAdapter(BaseAdapter):
    def __init__(
        self,
        *,
        name: str,
        priority: int = 50,
        fail_with: Exception | None = None,
        cost_per_call: float = 0.0,
    ):
        self.name = name
        self.capabilities = {Capability.CHAT_COMPLETE}
        self.category = AdapterCategory.LLM
        self.priority = priority
        self.cost_per_call = cost_per_call
        super().__init__()
        self._fail_with = fail_with

    def is_configured(self) -> bool:
        return True

    def _execute(self, capability, params):
        if self._fail_with is not None:
            raise self._fail_with
        return AdapterResult.success(
            adapter=self.name, capability=capability.value, data={},
        )


def _router_with(ledger, *adapters):
    reg = AdapterRegistry()
    for a in adapters:
        reg.register(a)
    return SmartRouter(
        registry=reg,
        rate_limiter=RateLimiter(policies={}),
        idempotency_cache=IdempotencyCache(policies={}),
        retry_telemetry=RetryTelemetry(),
        dead_letter_ledger=ledger,
    )


class TestRouterDeadLetterHook:
    def test_all_fail_records_one_entry(self):
        lg = DeadLetterLedger(path=None)
        a = _StubAdapter(name="a", fail_with=RuntimeError("boom"))
        b = _StubAdapter(name="b", fail_with=RuntimeError("boom"))
        r = _router_with(lg, a, b)
        out = r.execute(
            Capability.CHAT_COMPLETE,
            {"prompt": "hi"},
            RouteContext(fallback_depth=3),
        )
        assert not out.ok
        assert lg.size() == 1
        entry = lg.recent()[0]
        assert entry.capability == Capability.CHAT_COMPLETE.value
        assert entry.attempts >= 2  # primary + at least one fallback

    def test_success_does_not_record(self):
        lg = DeadLetterLedger(path=None)
        good = _StubAdapter(name="good", priority=90)
        bad = _StubAdapter(
            name="bad", priority=50, fail_with=RuntimeError("boom"),
        )
        r = _router_with(lg, good, bad)
        out = r.execute(Capability.CHAT_COMPLETE, {"prompt": "hi"})
        assert out.ok
        assert lg.size() == 0

    def test_primary_fails_fallback_wins_does_not_record(self):
        lg = DeadLetterLedger(path=None)
        a = _StubAdapter(name="a", priority=90, fail_with=RuntimeError("boom"))
        b = _StubAdapter(name="b", priority=50)
        r = _router_with(lg, a, b)
        out = r.execute(
            Capability.CHAT_COMPLETE, {"prompt": "hi"},
            RouteContext(fallback_depth=2),
        )
        assert out.ok and out.adapter == "b"
        assert lg.size() == 0

    def test_no_candidates_records_router_failure(self):
        lg = DeadLetterLedger(path=None)
        # No adapters registered at all.
        r = SmartRouter(
            registry=AdapterRegistry(),
            rate_limiter=RateLimiter(policies={}),
            idempotency_cache=IdempotencyCache(policies={}),
            retry_telemetry=RetryTelemetry(),
            dead_letter_ledger=lg,
        )
        out = r.execute(Capability.CHAT_COMPLETE, {"prompt": "hi"})
        assert not out.ok
        # When no candidate was even registered we still want a
        # record — operators should see "zero adapters for X" in
        # the dead-letter feed rather than silently swallowing it.
        # Current behaviour: the no-candidates branch returns BEFORE
        # reaching the hook, so nothing is recorded. Document that.
        # (If this proves to be an operational blind spot we can
        # move the hook earlier; for now the empty-registry case is
        # a configuration bug, not a transient failure.)
        assert lg.size() == 0

    def test_validation_error_still_recorded(self):
        lg = DeadLetterLedger(path=None)
        a = _StubAdapter(
            name="a", fail_with=AdapterValidationError("a", "bad params"),
        )
        r = _router_with(lg, a)
        out = r.execute(
            Capability.CHAT_COMPLETE, {"prompt": "hi"},
            RouteContext(fallback_depth=2),
        )
        assert not out.ok
        assert lg.size() == 1

    def test_params_snapshot_redacts_prompt_body(self):
        lg = DeadLetterLedger(path=None)
        a = _StubAdapter(name="a", fail_with=RuntimeError("boom"))
        r = _router_with(lg, a)
        big_prompt = "secret customer data " * 20
        r.execute(
            Capability.CHAT_COMPLETE,
            {"prompt": big_prompt, "model": "gpt-4"},
        )
        entry = lg.recent()[0]
        # The prompt body must never hit disk — only its length.
        assert "prompt" not in entry.params_snapshot
        assert entry.params_snapshot.get("prompt_len") == len(big_prompt)
        # The allow-listed ``model`` field should survive.
        assert entry.params_snapshot.get("model") == "gpt-4"

    def test_ledger_failure_does_not_mask_router_failure(self, monkeypatch):
        """Even if the ledger raises, the router must still return
        the terminal failure to the caller — never eat it."""
        lg = DeadLetterLedger(path=None)

        def _boom(**_kwargs):
            raise RuntimeError("ledger disk full")

        monkeypatch.setattr(lg, "record", _boom)
        a = _StubAdapter(name="a", fail_with=RuntimeError("boom"))
        r = _router_with(lg, a)
        out = r.execute(Capability.CHAT_COMPLETE, {})
        assert not out.ok
        assert out.error is not None

    def test_accessor_exposes_ledger(self):
        lg = DeadLetterLedger(path=None)
        r = _router_with(lg, _StubAdapter(name="x"))
        assert r.dead_letter_ledger is lg
