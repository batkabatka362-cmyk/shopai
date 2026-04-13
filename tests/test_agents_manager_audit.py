"""Tests for audit-pass-28 fixes in agents/manager/.

  AgentLoader:
    1. The "cache" stored the imported CLASS but returned cls()
       on every load() call — every cache hit constructed a NEW
       agent instance, throwing away any history the previous
       instance had learned. For BaseAgent (which carries
       _history) this silently broke the learning loop.
    2. No thread lock on _cache — concurrent first-loads could
       double-import + double-construct, then one would silently
       overwrite the other in the cache.

  AgentRegistry:
    3. lookup_by_capability used direct entry["capabilities"]
       access — KeyError on a future entry without that field.
    4. No thread lock on _registry mutations.

  AgentManager:
    5. start_agent / stop_agent / list_agents used direct
       a["status"] / a["type"] access — a manually-injected
       record without those fields crashed the whole call.
    6. No thread lock on _agents mutations.
"""
import threading
import types

import pytest


# ── AgentLoader instance cache ──────────────────────────────


class TestAgentLoaderInstanceCache:
    def test_load_returns_same_instance_on_repeated_calls(self, monkeypatch):
        """Regression: previously each load() returned cls() — a
        fresh instance — so any state on the prior instance was
        lost. Now the same name returns the same singleton."""
        from agents.manager.agent_loader import AgentLoader
        import importlib

        # Build a fake module with a class that tracks call counts
        construction_count = {"n": 0}

        class _StatefulAgent:
            def __init__(self):
                construction_count["n"] += 1
                self.history: list[str] = []

        fake_mod = types.ModuleType("fake_agent_module")
        fake_mod.StatefulAgent = _StatefulAgent

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "fake_agent_module":
                return fake_mod
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)

        loader = AgentLoader()
        a1 = loader.load("fake_agent_module.StatefulAgent")
        a1.history.append("first call")
        a2 = loader.load("fake_agent_module.StatefulAgent")

        # Same instance — history is preserved
        assert a1 is a2
        assert "first call" in a2.history
        assert construction_count["n"] == 1

    def test_concurrent_first_load_returns_same_instance(self, monkeypatch):
        from agents.manager.agent_loader import AgentLoader
        import importlib

        construction_count = {"n": 0}

        class _SlowAgent:
            def __init__(self):
                construction_count["n"] += 1
                # Sleep so the other thread has a chance to race past
                # the cache check before we write our instance.
                import time as _t
                _t.sleep(0.05)

        fake_mod = types.ModuleType("slow_agent_module")
        fake_mod.SlowAgent = _SlowAgent

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "slow_agent_module":
                return fake_mod
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)

        loader = AgentLoader()
        results: list = []

        def worker():
            results.append(loader.load("slow_agent_module.SlowAgent"))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 5 threads got the SAME instance
        assert all(r is results[0] for r in results)

    def test_clear_cache_works(self):
        from agents.manager.agent_loader import AgentLoader
        loader = AgentLoader()
        loader._cache["x"] = object()
        loader.clear_cache()
        assert loader._cache == {}


# ── AgentRegistry defensive + thread safe ───────────────────


class TestAgentRegistryDefensive:
    def test_lookup_by_capability_handles_missing_field(self):
        from agents.manager.agent_registry import AgentRegistry
        reg = AgentRegistry()
        reg.register("a", "x.A", ["pricing"])
        # Inject a malformed entry directly
        reg._registry["broken"] = {"name": "broken", "class_path": "x.B"}
        # Must not crash on the broken entry
        results = reg.lookup_by_capability("pricing")
        assert len(results) == 1
        assert results[0]["name"] == "a"

    def test_concurrent_register_no_lost_entries(self):
        from agents.manager.agent_registry import AgentRegistry
        reg = AgentRegistry()
        errors: list[Exception] = []

        def worker(start):
            try:
                for i in range(10):
                    reg.register(f"agent_{start}_{i}", f"x.A{start}{i}", ["cap"])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(reg.list_registered()) == 40


# ── AgentManager defensive + thread safe ────────────────────


class TestAgentManagerDefensive:
    def test_list_agents_handles_missing_type(self):
        from agents.manager.agent_manager import AgentManager
        m = AgentManager()
        m.register_agent("a1", "product", {})
        # Inject malformed record
        m._agents["broken"] = {"id": "broken"}  # no type
        # Filter must not crash
        results = m.list_agents(agent_type="product")
        assert len(results) == 1

    def test_start_agent_handles_missing_status(self):
        from agents.manager.agent_manager import AgentManager
        m = AgentManager()
        # Inject a malformed record with no status
        m._agents["x"] = {"id": "x", "type": "test"}
        # Should treat missing status as not-running and proceed
        result = m.start_agent("x")
        assert result["status"] == "running"

    def test_stop_agent_handles_missing_status(self):
        from agents.manager.agent_manager import AgentManager
        m = AgentManager()
        m._agents["x"] = {"id": "x", "type": "test"}
        result = m.stop_agent("x")
        assert result["status"] == "stopped"

    def test_get_agent_status_handles_missing_status(self):
        from agents.manager.agent_manager import AgentManager
        m = AgentManager()
        m._agents["x"] = {"id": "x", "type": "test"}
        assert m.get_agent_status("x") == "unknown"

    def test_register_agent_handles_non_dict_config(self):
        from agents.manager.agent_manager import AgentManager
        m = AgentManager()
        # Previously crashed on dict(config)
        result = m.register_agent("x", "type", "not a dict")
        assert result["config"] == {}

    def test_concurrent_register_unique_ids_no_loss(self):
        from agents.manager.agent_manager import AgentManager
        m = AgentManager()

        def worker(start):
            for i in range(20):
                m.register_agent(f"a_{start}_{i}", "test", {})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(m.list_agents()) == 80
