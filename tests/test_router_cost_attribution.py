"""Router cost-attribution hook — Option Z phase 2.

Tests that ``SmartRouter.execute`` tags every realised cost with
its caller identity so the dashboard can split spend by caller.
"""
from __future__ import annotations

import pytest

from core.adapters.base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from core.adapters.cost_ledger import DEFAULT_CALLER, CostLedger
from core.adapters.deadletter import DeadLetterLedger
from core.adapters.idempotency import IdempotencyCache
from core.adapters.rate_limit import RateLimiter
from core.adapters.registry import AdapterRegistry
from core.adapters.retry import RetryTelemetry
from core.adapters.router import RouteContext, SmartRouter


class _PaidAdapter(BaseAdapter):
    """Stub that always returns a fixed cost on success."""

    def __init__(
        self,
        *,
        name: str,
        cost_usd: float = 0.01,
        priority: int = 50,
        fail_with: Exception | None = None,
        tokens_in: int = 100,
        tokens_out: int = 20,
    ):
        self.name = name
        self.capabilities = {Capability.CHAT_COMPLETE}
        self.category = AdapterCategory.LLM
        self.priority = priority
        self.cost_per_call = cost_usd
        super().__init__()
        self._cost = cost_usd
        self._fail = fail_with
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out

    def is_configured(self) -> bool:
        return True

    def _execute(self, capability, params):
        if self._fail is not None:
            raise self._fail
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"ok": True},
            cost_usd=self._cost,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
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
        dead_letter_ledger=DeadLetterLedger(path=None),
        cost_ledger=ledger,
    )


class TestRouterCostAttribution:
    def test_success_with_caller_tags_cost(self):
        lg = CostLedger()
        a = _PaidAdapter(name="openai", cost_usd=0.025)
        r = _router_with(lg, a)
        out = r.execute(
            Capability.CHAT_COMPLETE,
            {"prompt": "hi"},
            RouteContext(caller="support_agent"),
        )
        assert out.ok
        rows = lg.rows()
        assert len(rows) == 1
        assert rows[0]["caller"] == "support_agent"
        assert rows[0]["adapter"] == "openai"
        assert rows[0]["capability"] == "chat_complete"
        assert rows[0]["total_usd"] == pytest.approx(0.025)
        assert rows[0]["tokens_in"] == 100
        assert rows[0]["tokens_out"] == 20

    def test_absent_caller_collapses_to_unknown(self):
        lg = CostLedger()
        a = _PaidAdapter(name="openai", cost_usd=0.01)
        r = _router_with(lg, a)
        out = r.execute(Capability.CHAT_COMPLETE, {"prompt": "hi"})
        assert out.ok
        rows = lg.rows()
        assert len(rows) == 1
        assert rows[0]["caller"] == DEFAULT_CALLER

    def test_failure_does_not_record_cost(self):
        lg = CostLedger()
        a = _PaidAdapter(
            name="openai", cost_usd=0.01,
            fail_with=RuntimeError("boom"),
        )
        r = _router_with(lg, a)
        out = r.execute(
            Capability.CHAT_COMPLETE, {"prompt": "hi"},
            RouteContext(caller="agent"),
        )
        assert not out.ok
        assert lg.rows() == []

    def test_same_caller_accumulates(self):
        lg = CostLedger()
        a = _PaidAdapter(name="openai", cost_usd=0.01)
        r = _router_with(lg, a)
        for _ in range(3):
            r.execute(
                Capability.CHAT_COMPLETE, {"prompt": "hi"},
                RouteContext(caller="agent"),
            )
        rows = lg.rows()
        assert len(rows) == 1
        assert rows[0]["calls"] == 3
        assert rows[0]["total_usd"] == pytest.approx(0.03)

    def test_different_callers_split(self):
        lg = CostLedger()
        a = _PaidAdapter(name="openai", cost_usd=0.01)
        r = _router_with(lg, a)
        r.execute(
            Capability.CHAT_COMPLETE, {"prompt": "p"},
            RouteContext(caller="reflect"),
        )
        r.execute(
            Capability.CHAT_COMPLETE, {"prompt": "p"},
            RouteContext(caller="support"),
        )
        rows = lg.rows()
        assert len(rows) == 2
        callers = {r["caller"] for r in rows}
        assert callers == {"reflect", "support"}

    def test_zero_cost_call_not_recorded(self):
        lg = CostLedger()
        a = _PaidAdapter(name="local", cost_usd=0.0)
        r = _router_with(lg, a)
        out = r.execute(
            Capability.CHAT_COMPLETE, {"prompt": "p"},
            RouteContext(caller="agent"),
        )
        assert out.ok
        # Zero-cost calls (e.g. self-hosted LLMs) don't pollute
        # the attribution table.
        assert lg.rows() == []

    def test_fallback_success_tags_winning_adapter(self):
        lg = CostLedger()
        bad = _PaidAdapter(
            name="bad", priority=90, cost_usd=0.05,
            fail_with=RuntimeError("boom"),
        )
        good = _PaidAdapter(
            name="good", priority=50, cost_usd=0.02,
        )
        r = _router_with(lg, bad, good)
        out = r.execute(
            Capability.CHAT_COMPLETE, {"prompt": "p"},
            RouteContext(caller="agent", fallback_depth=2),
        )
        assert out.ok and out.adapter == "good"
        rows = lg.rows()
        # Only the adapter that actually succeeded is billed.
        assert len(rows) == 1
        assert rows[0]["adapter"] == "good"
        assert rows[0]["total_usd"] == pytest.approx(0.02)

    def test_malformed_caller_collapses_safely(self):
        lg = CostLedger()
        a = _PaidAdapter(name="openai", cost_usd=0.01)
        r = _router_with(lg, a)
        r.execute(
            Capability.CHAT_COMPLETE, {"prompt": "p"},
            RouteContext(caller="has spaces & ;drops"),
        )
        rows = lg.rows()
        assert rows[0]["caller"] == DEFAULT_CALLER

    def test_ledger_failure_does_not_mask_success(self, monkeypatch):
        """A ledger glitch must never turn a good result into a
        failure — cost telemetry is strictly additive."""
        lg = CostLedger()

        def _boom(**_kwargs):
            raise RuntimeError("ledger down")

        monkeypatch.setattr(lg, "record", _boom)
        a = _PaidAdapter(name="openai", cost_usd=0.01)
        r = _router_with(lg, a)
        out = r.execute(
            Capability.CHAT_COMPLETE, {"prompt": "p"},
            RouteContext(caller="agent"),
        )
        assert out.ok

    def test_accessor_exposes_ledger(self):
        lg = CostLedger()
        a = _PaidAdapter(name="openai")
        r = _router_with(lg, a)
        assert r.cost_ledger is lg
