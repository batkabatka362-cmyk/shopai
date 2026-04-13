"""Wave 14b tests — StatsProvider protocol + StatsRegistry.

Verifies:
1. StatsProvider is a runtime-checkable Protocol that matches any
   object with ``get_stats() -> dict[str, Any]``.
2. StatsRegistry can register, unregister, collect, and discover
   providers.
3. stats_envelope wraps raw dicts correctly.
4. Registry singleton (DCLP) returns same instance across threads.
5. Collection is resilient — one broken provider doesn't crash the
   rest.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest


# ═══════════════════════════════════════════════
# Protocol conformance
# ═══════════════════════════════════════════════

class TestStatsProviderProtocol:
    """StatsProvider runtime_checkable behavior."""

    def test_class_with_get_stats_satisfies_protocol(self):
        from core.telemetry.stats_protocol import StatsProvider

        class Good:
            def get_stats(self) -> dict[str, Any]:
                return {"ok": True}

        assert isinstance(Good(), StatsProvider)

    def test_class_without_get_stats_fails(self):
        from core.telemetry.stats_protocol import StatsProvider

        class Bad:
            def status(self) -> dict:
                return {}

        assert not isinstance(Bad(), StatsProvider)

    def test_existing_modules_satisfy_protocol(self):
        """Key core modules should satisfy StatsProvider."""
        from core.telemetry.stats_protocol import StatsProvider

        from core.brain.strategy_planner import StrategyPlanner
        from core.ai.product_finder import AIProductFinder
        from core.system.production import AuditTrail

        assert isinstance(StrategyPlanner(), StatsProvider)
        assert isinstance(AIProductFinder(), StatsProvider)
        assert isinstance(AuditTrail(), StatsProvider)


# ═══════════════════════════════════════════════
# stats_envelope
# ═══════════════════════════════════════════════

class TestStatsEnvelope:

    def test_wraps_with_component_and_timestamp(self):
        from core.telemetry.stats_protocol import stats_envelope

        before = time.time()
        result = stats_envelope("test.component", {"count": 42})
        after = time.time()

        assert result["component"] == "test.component"
        assert before <= result["timestamp"] <= after
        assert result["stats"] == {"count": 42}

    def test_preserves_raw_dict_identity(self):
        from core.telemetry.stats_protocol import stats_envelope

        raw = {"a": 1, "nested": {"b": 2}}
        result = stats_envelope("x", raw)
        assert result["stats"] is raw

    def test_empty_raw_dict(self):
        from core.telemetry.stats_protocol import stats_envelope

        result = stats_envelope("empty", {})
        assert result["stats"] == {}
        assert result["component"] == "empty"


# ═══════════════════════════════════════════════
# StatsRegistry — core behavior
# ═══════════════════════════════════════════════

class _FakeProvider:
    """Minimal StatsProvider for testing."""

    def __init__(self, stats: dict[str, Any] | None = None):
        self._stats = stats or {"status": "ok"}

    def get_stats(self) -> dict[str, Any]:
        return dict(self._stats)


class _BrokenProvider:
    """Provider whose get_stats raises."""

    def get_stats(self) -> dict[str, Any]:
        raise RuntimeError("broken on purpose")


class TestStatsRegistryBasics:

    def _fresh_registry(self):
        from core.telemetry.stats_protocol import StatsRegistry
        return StatsRegistry()

    def test_register_and_list(self):
        reg = self._fresh_registry()
        reg.register("alpha", _FakeProvider())
        reg.register("beta", _FakeProvider())

        assert reg.list_providers() == ["alpha", "beta"]
        assert len(reg) == 2

    def test_unregister(self):
        reg = self._fresh_registry()
        reg.register("x", _FakeProvider())
        reg.unregister("x")

        assert reg.list_providers() == []
        assert len(reg) == 0

    def test_unregister_missing_is_noop(self):
        reg = self._fresh_registry()
        reg.unregister("nonexistent")  # should not raise

    def test_collect_single(self):
        reg = self._fresh_registry()
        reg.register("mymod", _FakeProvider({"count": 7}))

        result = reg.collect("mymod")
        assert result is not None
        assert result["component"] == "mymod"
        assert result["stats"]["count"] == 7
        assert "timestamp" in result

    def test_collect_missing_returns_none(self):
        reg = self._fresh_registry()
        assert reg.collect("missing") is None

    def test_collect_all_gathers_registered(self):
        reg = self._fresh_registry()
        reg.register("a", _FakeProvider({"val": 1}))
        reg.register("b", _FakeProvider({"val": 2}))

        snapshot = reg.collect_all(auto_discover=False)

        assert snapshot["component_count"] == 2
        assert "a" in snapshot["components"]
        assert "b" in snapshot["components"]
        assert snapshot["components"]["a"]["val"] == 1
        assert snapshot["components"]["b"]["val"] == 2
        assert snapshot["collection_errors"] == []
        assert "timestamp" in snapshot

    def test_collect_all_resilient_to_broken_provider(self):
        reg = self._fresh_registry()
        reg.register("good", _FakeProvider({"ok": True}))
        reg.register("bad", _BrokenProvider())

        snapshot = reg.collect_all(auto_discover=False)

        # Good provider still collected
        assert "good" in snapshot["components"]
        assert snapshot["components"]["good"]["ok"] is True

        # Bad provider captured in errors
        assert len(snapshot["collection_errors"]) == 1
        assert snapshot["collection_errors"][0]["component"] == "bad"
        assert "broken on purpose" in snapshot["collection_errors"][0]["error"]

        # Count only reflects successful collections
        assert snapshot["component_count"] == 1

    def test_collect_all_empty_registry(self):
        reg = self._fresh_registry()
        snapshot = reg.collect_all(auto_discover=False)

        assert snapshot["component_count"] == 0
        assert snapshot["components"] == {}
        assert snapshot["collection_errors"] == []


# ═══════════════════════════════════════════════
# StatsRegistry — discovery
# ═══════════════════════════════════════════════

class TestStatsRegistryDiscovery:

    def _fresh_registry(self):
        from core.telemetry.stats_protocol import StatsRegistry
        return StatsRegistry()

    def test_discover_registers_known_providers(self):
        reg = self._fresh_registry()
        count = reg.discover()

        # At least some known providers should succeed
        assert count > 0
        assert len(reg) > 0

    def test_discovered_providers_have_get_stats(self):
        from core.telemetry.stats_protocol import StatsProvider
        reg = self._fresh_registry()
        reg.discover()

        for name in reg.list_providers():
            result = reg.collect(name)
            assert result is not None, f"{name} collect returned None"
            assert "stats" in result, f"{name} envelope missing 'stats'"
            assert isinstance(result["stats"], dict), f"{name} stats not a dict"

    def test_discover_is_idempotent(self):
        reg = self._fresh_registry()
        first = reg.discover()
        second = reg.discover()

        # Second call should register 0 new (already present)
        assert second == 0
        assert len(reg) == first

    def test_collect_all_with_auto_discover(self):
        reg = self._fresh_registry()
        snapshot = reg.collect_all(auto_discover=True)

        # auto_discover should trigger lazy discovery
        assert snapshot["component_count"] > 0


# ═══════════════════════════════════════════════
# Singleton (DCLP)
# ═══════════════════════════════════════════════

class TestStatsRegistrySingleton:

    def test_singleton_returns_same_instance(self):
        from core.telemetry.stats_protocol import get_stats_registry
        a = get_stats_registry()
        b = get_stats_registry()
        assert a is b

    def test_singleton_thread_safe(self):
        """Multiple threads racing get_stats_registry all get same object."""
        import core.telemetry.stats_protocol as mod

        # Reset singleton for this test
        original = mod._registry
        mod._registry = None

        try:
            barrier = threading.Barrier(8)
            results = [None] * 8

            def race(idx):
                barrier.wait()
                results[idx] = mod.get_stats_registry()

            threads = [threading.Thread(target=race, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

            assert all(r is results[0] for r in results)
        finally:
            mod._registry = original

    def test_module_has_dclp_lock(self):
        import core.telemetry.stats_protocol as mod
        assert hasattr(mod, "_registry_lock")
        assert isinstance(mod._registry_lock, type(threading.Lock()))


# ═══════════════════════════════════════════════
# Integration — real modules
# ═══════════════════════════════════════════════

class TestRealModuleIntegration:
    """Verify real ShopAI modules work with the registry."""

    def test_strategy_planner_registers_and_collects(self):
        from core.telemetry.stats_protocol import StatsRegistry
        from core.brain.strategy_planner import get_strategy_planner

        reg = StatsRegistry()
        reg.register("brain.strategy_planner", get_strategy_planner())

        result = reg.collect("brain.strategy_planner")
        assert result is not None
        assert "total" in result["stats"]
        assert "by_type" in result["stats"]

    def test_product_finder_registers_and_collects(self):
        from core.telemetry.stats_protocol import StatsRegistry
        from core.ai.product_finder import get_product_finder

        reg = StatsRegistry()
        reg.register("ai.product_finder", get_product_finder())

        result = reg.collect("ai.product_finder")
        assert result is not None
        assert "total_found" in result["stats"]

    def test_audit_trail_registers_and_collects(self):
        from core.telemetry.stats_protocol import StatsRegistry
        from core.system.production import get_audit

        reg = StatsRegistry()
        reg.register("production.audit", get_audit())

        result = reg.collect("production.audit")
        assert result is not None
        assert "total" in result["stats"]
        assert "by_action" in result["stats"]

    def test_full_system_snapshot(self):
        """collect_all with discovery produces a valid system snapshot."""
        from core.telemetry.stats_protocol import StatsRegistry

        reg = StatsRegistry()
        reg.discover()
        snapshot = reg.collect_all(auto_discover=False)

        assert snapshot["component_count"] >= 3
        assert isinstance(snapshot["timestamp"], float)

        # Every component's stats should be a dict
        for name, stats in snapshot["components"].items():
            assert isinstance(stats, dict), f"{name} stats is not a dict"
