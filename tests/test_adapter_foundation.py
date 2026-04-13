"""Tests for the core/adapters foundation: base, errors,
registry, config, metrics, router.

These tests intentionally do NOT make real HTTP calls. Concrete
adapters are tested in ``tests/test_llm_adapters.py``.
"""
from __future__ import annotations

import os
import time

import pytest

from core.adapters import (
    AdapterAuthError,
    AdapterCategory,
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterRegistry,
    AdapterResult,
    AdapterUnavailable,
    AdapterValidationError,
    BaseAdapter,
    Capability,
    NoAdapterAvailable,
    RouteContext,
    SmartRouter,
    get_config,
    get_metrics,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


# ── Fake adapters used by every test below ────────────────────


class _FakeAdapter(BaseAdapter):
    """Minimal in-process adapter that records the calls it
    received and lets tests inject custom failure modes."""

    name = "fake"
    category = AdapterCategory.LLM
    capabilities = {Capability.CHAT_COMPLETE}

    def __init__(
        self,
        *,
        name: str = "fake",
        capabilities: set[Capability] | None = None,
        configured: bool = True,
        priority: int = 50,
        cost_per_call: float = 0.0,
        raise_error: AdapterError | None = None,
        result_data: dict | None = None,
    ) -> None:
        # Have to set these BEFORE super().__init__ which validates
        self.name = name
        self.capabilities = capabilities or {Capability.CHAT_COMPLETE}
        self.priority = priority
        self.cost_per_call = cost_per_call
        super().__init__()
        self._configured = configured
        self._raise_error = raise_error
        self._result_data = result_data or {"text": "ok"}
        self.calls: list[tuple[Capability, dict]] = []

    def is_configured(self) -> bool:
        return self._configured

    def _execute(self, capability, params):
        self.calls.append((capability, params))
        if self._raise_error is not None:
            raise self._raise_error
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data=dict(self._result_data),
        )


@pytest.fixture(autouse=True)
def _clean_singletons(monkeypatch):
    """Reset every adapter singleton between tests so state
    doesn't leak."""
    # Drop any env vars that real LLM adapters might pick up
    for var in (
        "GROQ_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY", "OPENROUTER_API_KEY", "HUGGINGFACE_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


# ── BaseAdapter ─────────────────────────────────────────────


class TestBaseAdapter:
    def test_must_have_name(self):
        class _NoName(BaseAdapter):
            name = ""
            capabilities = {Capability.CHAT_COMPLETE}
            def _execute(self, c, p): ...
        with pytest.raises(ValueError, match="name must be set"):
            _NoName()

    def test_must_have_capabilities(self):
        class _NoCaps(BaseAdapter):
            name = "no_caps"
            capabilities = set()
            def _execute(self, c, p): ...
        with pytest.raises(ValueError, match="capabilities"):
            _NoCaps()

    def test_supports_capability(self):
        a = _FakeAdapter(capabilities={Capability.CHAT_COMPLETE})
        assert a.supports(Capability.CHAT_COMPLETE)
        assert a.supports("chat_complete")
        assert not a.supports(Capability.CODE_GENERATE)
        assert not a.supports("definitely_not_a_capability")

    def test_execute_normalises_string_capability(self):
        a = _FakeAdapter()
        result = a.execute("chat_complete", {"prompt": "hi"})
        assert result.ok
        assert result.adapter == "fake"
        assert result.capability == "chat_complete"

    def test_execute_unknown_capability_returns_validation_error(self):
        a = _FakeAdapter()
        result = a.execute("not_a_capability")
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_execute_unsupported_capability_returns_validation_error(self):
        a = _FakeAdapter(capabilities={Capability.CHAT_COMPLETE})
        result = a.execute(Capability.CODE_GENERATE)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "does not implement" in result.error.reason

    def test_execute_unconfigured_returns_not_configured(self):
        a = _FakeAdapter(configured=False)
        result = a.execute(Capability.CHAT_COMPLETE)
        assert not result.ok
        assert isinstance(result.error, AdapterNotConfigured)

    def test_execute_wraps_typed_errors(self):
        a = _FakeAdapter(
            raise_error=AdapterRateLimited("fake", "slow down"),
        )
        result = a.execute(Capability.CHAT_COMPLETE)
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)
        assert "slow down" in result.error.reason
        # Latency should still be populated even on failure
        assert result.latency_ms >= 0

    def test_execute_wraps_unexpected_exception(self):
        class _Boom(BaseAdapter):
            name = "boom"
            category = AdapterCategory.OTHER
            capabilities = {Capability.CHAT_COMPLETE}
            def _execute(self, c, p):
                raise RuntimeError("kaboom")
        a = _Boom()
        result = a.execute(Capability.CHAT_COMPLETE)
        assert not result.ok
        assert isinstance(result.error, AdapterError)
        assert "RuntimeError" in result.error.reason

    def test_execute_populates_latency(self):
        a = _FakeAdapter()
        result = a.execute(Capability.CHAT_COMPLETE)
        assert result.latency_ms >= 0  # may be 0 on very fast machines

    def test_describe_is_json_safe(self):
        a = _FakeAdapter()
        d = a.describe()
        assert d["name"] == "fake"
        assert d["category"] == "llm"
        assert "chat_complete" in d["capabilities"]
        assert d["configured"] is True


# ── AdapterRegistry ─────────────────────────────────────────


class TestRegistry:
    def test_register_and_get(self):
        reg = AdapterRegistry()
        a = _FakeAdapter()
        reg.register(a)
        assert reg.get("fake") is a
        assert reg.has("fake")
        assert "fake" in reg
        assert len(reg) == 1

    def test_register_duplicate_raises(self):
        reg = AdapterRegistry()
        reg.register(_FakeAdapter())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_FakeAdapter())

    def test_register_replace_overwrites(self):
        reg = AdapterRegistry()
        first = _FakeAdapter(result_data={"text": "first"})
        second = _FakeAdapter(result_data={"text": "second"})
        reg.register(first)
        reg.register(second, replace=True)
        # The second instance is what we get back
        assert reg.get("fake") is second

    def test_register_rejects_non_adapter(self):
        reg = AdapterRegistry()
        with pytest.raises(TypeError):
            reg.register("not an adapter")  # type: ignore[arg-type]

    def test_unregister(self):
        reg = AdapterRegistry()
        reg.register(_FakeAdapter())
        assert reg.unregister("fake") is True
        assert reg.unregister("fake") is False
        assert len(reg) == 0

    def test_swap(self):
        reg = AdapterRegistry()
        old = _FakeAdapter(name="old")
        new = _FakeAdapter(name="new")
        reg.register(old)
        previous = reg.swap("old", new)
        assert previous is old
        assert reg.get("new") is new
        assert reg.get("old") is None

    def test_find_by_capability_sorts_priority(self):
        reg = AdapterRegistry()
        low = _FakeAdapter(name="low", priority=10)
        high = _FakeAdapter(name="high", priority=99)
        mid = _FakeAdapter(name="mid", priority=50)
        reg.register(low)
        reg.register(high)
        reg.register(mid)
        result = reg.find_by_capability(Capability.CHAT_COMPLETE)
        assert [a.name for a in result] == ["high", "mid", "low"]

    def test_find_by_capability_filters_unconfigured_by_default(self):
        reg = AdapterRegistry()
        configured = _FakeAdapter(name="ok", configured=True)
        unconfigured = _FakeAdapter(name="bad", configured=False)
        reg.register(configured)
        reg.register(unconfigured)
        result = reg.find_by_capability(Capability.CHAT_COMPLETE)
        assert [a.name for a in result] == ["ok"]

    def test_find_by_capability_includes_unconfigured_when_asked(self):
        reg = AdapterRegistry()
        reg.register(_FakeAdapter(name="ok", configured=True))
        reg.register(_FakeAdapter(name="bad", configured=False))
        result = reg.find_by_capability(
            Capability.CHAT_COMPLETE, configured_only=False,
        )
        assert {a.name for a in result} == {"ok", "bad"}

    def test_find_by_capability_unknown_returns_empty(self):
        reg = AdapterRegistry()
        reg.register(_FakeAdapter())
        assert reg.find_by_capability("nope") == []

    def test_find_by_capability_cheaper_wins_ties(self):
        reg = AdapterRegistry()
        cheap = _FakeAdapter(name="cheap", priority=50, cost_per_call=0.0)
        pricey = _FakeAdapter(name="pricey", priority=50, cost_per_call=0.1)
        reg.register(pricey)
        reg.register(cheap)
        result = reg.find_by_capability(Capability.CHAT_COMPLETE)
        assert [a.name for a in result] == ["cheap", "pricey"]

    def test_singleton_isolation(self):
        from core.adapters import get_registry
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_iter_and_list(self):
        reg = AdapterRegistry()
        reg.register(_FakeAdapter(name="a"))
        reg.register(_FakeAdapter(name="b"))
        names = sorted(a.name for a in reg)
        assert names == ["a", "b"]
        descriptions = reg.list()
        assert len(descriptions) == 2


# ── AdapterConfig ───────────────────────────────────────────


class TestConfig:
    def test_get_returns_empty_when_unset(self):
        cfg = get_config()
        assert cfg.get("groq") == ""
        assert cfg.has("groq") is False

    def test_get_with_default(self):
        cfg = get_config()
        assert cfg.get("nonexistent", default="x") == "x"

    def test_reload_picks_up_env_change(self, monkeypatch):
        cfg = get_config()
        assert cfg.get("groq") == ""
        monkeypatch.setenv("GROQ_API_KEY", "abc123")
        cfg.reload()
        assert cfg.get("groq") == "abc123"
        assert cfg.has("groq")

    def test_repr_does_not_leak_secrets(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "super-secret-key-do-not-leak")
        cfg = get_config()
        cfg.reload()
        assert "super-secret-key" not in repr(cfg)

    def test_describe_lists_configured(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "x")
        cfg = get_config()
        cfg.reload()
        d = cfg.describe()
        assert "groq" in d["configured"]
        assert d["configured_count"] >= 1


# ── MetricsCollector ────────────────────────────────────────


class TestMetrics:
    def test_record_success(self):
        m = get_metrics()
        m.record("fake", success=True, latency_ms=5.0, cost_usd=0.001)
        stats = m.stats_for("fake")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1
        assert stats["calls_failure"] == 0
        assert stats["success_rate"] == 1.0
        assert stats["cost_usd_total"] == 0.001

    def test_record_failure(self):
        m = get_metrics()
        m.record("fake", success=False, error="boom")
        stats = m.stats_for("fake")
        assert stats["calls_failure"] == 1
        assert stats["last_error"] == "boom"

    def test_percentile_calculation(self):
        m = get_metrics()
        for ms in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
            m.record("fake", success=True, latency_ms=ms)
        stats = m.stats_for("fake")
        assert stats["latency_p50_ms"] > 0
        assert stats["latency_p95_ms"] >= stats["latency_p50_ms"]

    def test_quota_used_pct(self):
        m = get_metrics()
        for _ in range(5):
            m.record("fake", success=True)
        assert m.quota_used_pct("fake", daily_limit=10) == 0.5
        assert m.quota_used_pct("fake", daily_limit=0) == 0.0
        assert m.quota_used_pct("nonexistent", daily_limit=100) == 0.0

    def test_record_failsoft_on_bad_input(self):
        """Metrics must never crash a real call. Even if record
        gets garbage, it should swallow and continue."""
        m = get_metrics()
        # Should not raise even with weird types
        m.record("fake", success=True, latency_ms=None, cost_usd="bad")  # type: ignore[arg-type]
        # Stats should still exist for the adapter
        stats = m.stats_for("fake")
        assert stats is not None

    def test_reset(self):
        m = get_metrics()
        m.record("fake", success=True)
        m.reset("fake")
        assert m.stats_for("fake") is None


# ── SmartRouter ─────────────────────────────────────────────


class TestRouter:
    def test_route_picks_highest_priority(self):
        reg = get_registry()
        reg.register(_FakeAdapter(name="low", priority=10))
        reg.register(_FakeAdapter(name="high", priority=99))
        router = SmartRouter(registry=reg)
        chosen = router.route(Capability.CHAT_COMPLETE)
        assert chosen.name == "high"

    def test_route_raises_when_no_adapter(self):
        router = SmartRouter(registry=get_registry())
        with pytest.raises(NoAdapterAvailable):
            router.route(Capability.CHAT_COMPLETE)

    def test_route_respects_exclude(self):
        reg = get_registry()
        reg.register(_FakeAdapter(name="a", priority=99))
        reg.register(_FakeAdapter(name="b", priority=50))
        router = SmartRouter(registry=reg)
        chosen = router.route(
            Capability.CHAT_COMPLETE,
            RouteContext(exclude={"a"}),
        )
        assert chosen.name == "b"

    def test_route_respects_prefer(self):
        reg = get_registry()
        reg.register(_FakeAdapter(name="a", priority=99))
        reg.register(_FakeAdapter(name="b", priority=50))
        router = SmartRouter(registry=reg)
        # Even though "a" has higher priority, prefer should boost
        # "b" by +50 → b score = 100, a score = 99 → b wins
        chosen = router.route(
            Capability.CHAT_COMPLETE,
            RouteContext(prefer=["b"]),
        )
        assert chosen.name == "b"

    def test_route_respects_budget(self):
        reg = get_registry()
        reg.register(_FakeAdapter(name="cheap", cost_per_call=0.001))
        reg.register(_FakeAdapter(name="expensive", cost_per_call=1.0))
        router = SmartRouter(registry=reg)
        chosen = router.route(
            Capability.CHAT_COMPLETE,
            RouteContext(budget_usd=0.01),
        )
        assert chosen.name == "cheap"

    def test_route_skips_unconfigured(self):
        reg = get_registry()
        reg.register(_FakeAdapter(name="ok", configured=True, priority=10))
        reg.register(_FakeAdapter(name="bad", configured=False, priority=99))
        router = SmartRouter(registry=reg)
        chosen = router.route(Capability.CHAT_COMPLETE)
        assert chosen.name == "ok"

    def test_pii_routes_to_pii_safe_only(self):
        reg = get_registry()
        # Plain cloud LLM — not PII safe
        reg.register(_FakeAdapter(name="cloud", priority=99))

        # Local adapter — name starts with "local_" so router
        # treats it as PII safe
        reg.register(_FakeAdapter(name="local_llama", priority=10))

        router = SmartRouter(registry=reg)
        chosen = router.route(
            Capability.CHAT_COMPLETE,
            RouteContext(contains_pii=True),
        )
        assert chosen.name == "local_llama"

    def test_pii_with_no_safe_adapter_raises(self):
        reg = get_registry()
        reg.register(_FakeAdapter(name="cloud", priority=99))
        router = SmartRouter(registry=reg)
        with pytest.raises(NoAdapterAvailable):
            router.route(
                Capability.CHAT_COMPLETE,
                RouteContext(contains_pii=True),
            )

    def test_execute_falls_back_on_failure(self):
        reg = get_registry()
        broken = _FakeAdapter(
            name="broken",
            priority=99,
            raise_error=AdapterUnavailable("broken", "down"),
        )
        working = _FakeAdapter(name="working", priority=50)
        reg.register(broken)
        reg.register(working)
        router = SmartRouter(registry=reg)
        result = router.execute(
            Capability.CHAT_COMPLETE,
            {"prompt": "hi"},
            RouteContext(fallback_depth=2),
        )
        assert result.ok
        assert result.adapter == "working"

    def test_execute_does_not_fall_back_on_validation_error(self):
        """Validation errors are caller bugs — falling back to a
        second adapter would just repeat the bug. Router stops."""
        reg = get_registry()
        first = _FakeAdapter(
            name="first",
            priority=99,
            raise_error=AdapterValidationError("first", "bad params"),
        )
        second = _FakeAdapter(name="second", priority=50)
        reg.register(first)
        reg.register(second)
        router = SmartRouter(registry=reg)
        result = router.execute(
            Capability.CHAT_COMPLETE,
            {"prompt": "x"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        # second.calls is empty — router did not fall back
        assert second.calls == []

    def test_execute_returns_no_adapter_when_empty(self):
        router = SmartRouter(registry=get_registry())
        result = router.execute(Capability.CHAT_COMPLETE)
        assert not result.ok
        assert isinstance(result.error, NoAdapterAvailable)

    def test_execute_records_metrics(self):
        reg = get_registry()
        reg.register(_FakeAdapter(name="m1"))
        router = SmartRouter(registry=reg, metrics=get_metrics())
        router.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})
        stats = get_metrics().stats_for("m1")
        assert stats is not None
        assert stats["calls_total"] == 1

    def test_candidates_returns_full_chain(self):
        reg = get_registry()
        reg.register(_FakeAdapter(name="a", priority=10))
        reg.register(_FakeAdapter(name="b", priority=99))
        reg.register(_FakeAdapter(name="c", priority=50))
        router = SmartRouter(registry=reg)
        names = [a.name for a in router.candidates(Capability.CHAT_COMPLETE)]
        assert names == ["b", "c", "a"]


# ── Result envelope ─────────────────────────────────────────


class TestAdapterResult:
    def test_success_factory(self):
        r = AdapterResult.success(
            adapter="x", capability="chat_complete", data={"text": "hi"},
        )
        assert r.ok
        assert r.adapter == "x"
        assert r.data["text"] == "hi"
        assert r.error is None

    def test_failure_factory(self):
        err = AdapterError("x", "boom")
        r = AdapterResult.failure(
            adapter="x", capability="chat_complete", error=err,
        )
        assert not r.ok
        assert r.error is err
