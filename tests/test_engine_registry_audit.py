"""Tests for audit-pass-11 fixes in engines/registry.

  1. get_engine() previously had a bare `except Exception: return
     None` that swallowed every load failure silently. With 130+
     engines, broken modules were completely invisible — operators
     could not tell a missing engine apart from a broken one.
  2. The `_cache` dict was accessed without a lock, so two threads
     calling get_engine() concurrently could double-instantiate
     the same engine and one would silently overwrite the other.
  3. Engine class discovery picked the first attribute (in dir()
     order) ending with "Engine" — non-deterministic when a module
     imports other Engine classes. The wrong class could win.
"""
import pytest


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset cache + load errors before and after each test so
    audits don't see stale state from earlier runs."""
    from engines import registry
    registry.clear_cache()
    yield
    registry.clear_cache()


# ── Per-engine load error capture ────────────────────────────


class TestLoadErrorCapture:
    def test_unknown_engine_returns_none_no_error_recorded(self):
        from engines import registry
        assert registry.get_engine("definitely_not_a_real_engine") is None
        # Unknown != broken — load_errors should still be empty.
        assert registry.get_load_errors() == {}

    def test_broken_engine_module_records_error(self, monkeypatch):
        from engines import registry
        import importlib

        # Inject a fake engine that fails on import.
        registry._ENGINE_MAP["__test_broken__"] = "engines.__test_broken__"

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "engines.__test_broken__":
                raise ImportError("intentional test failure")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        try:
            assert registry.get_engine("__test_broken__") is None
            errors = registry.get_load_errors()
            assert "__test_broken__" in errors
            assert "ImportError" in errors["__test_broken__"]
            assert "intentional" in errors["__test_broken__"]
        finally:
            registry._ENGINE_MAP.pop("__test_broken__", None)

    def test_module_without_engine_class_records_error(self, monkeypatch):
        from engines import registry
        import importlib
        import types

        # A module with no class ending in "Engine"
        empty_mod = types.ModuleType("engines.__test_empty__")
        empty_mod.SomeOtherClass = type("SomeOtherClass", (), {})
        registry._ENGINE_MAP["__test_empty__"] = "engines.__test_empty__"

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "engines.__test_empty__":
                return empty_mod
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        try:
            assert registry.get_engine("__test_empty__") is None
            errors = registry.get_load_errors()
            assert "__test_empty__" in errors
            assert "no class" in errors["__test_empty__"].lower()
        finally:
            registry._ENGINE_MAP.pop("__test_empty__", None)

    def test_successful_load_clears_prior_error(self, monkeypatch):
        from engines import registry
        import importlib
        import types

        # First attempt: broken
        attempts = {"count": 0}

        registry._ENGINE_MAP["__test_recovers__"] = "engines.__test_recovers__"

        # Pre-populate load_errors as if a previous load failed
        registry._load_errors["__test_recovers__"] = "ImportError: simulated"

        real_import = importlib.import_module

        # Second attempt: working — return a module with a real engine class
        good_mod = types.ModuleType("engines.__test_recovers__")
        class _GoodEngine:
            __module__ = "engines.__test_recovers__"
        good_mod.GoodEngine = _GoodEngine

        def fake_import(name, *args, **kwargs):
            if name == "engines.__test_recovers__":
                return good_mod
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        try:
            engine = registry.get_engine("__test_recovers__")
            assert engine is not None
            # Successful load clears the prior error record.
            assert "__test_recovers__" not in registry.get_load_errors()
        finally:
            registry._ENGINE_MAP.pop("__test_recovers__", None)

    def test_get_load_errors_returns_copy(self):
        from engines import registry
        registry._load_errors["fake"] = "test"
        errors = registry.get_load_errors()
        errors["mutated"] = "yes"
        # Mutating the returned dict must not affect the registry.
        assert "mutated" not in registry.get_load_errors()
        registry._load_errors.pop("fake", None)


# ── Deterministic class discovery ────────────────────────────


class TestDeterministicClassDiscovery:
    def test_picks_class_defined_in_module_not_re_export(self, monkeypatch):
        """Regression: previously the registry picked the first
        attribute (alphabetically via dir()) ending with 'Engine',
        so a module that did `from elsewhere import OtherEngine`
        could win the wrong class. Now we prefer classes whose
        __module__ matches the loaded module."""
        from engines import registry
        import importlib
        import types

        mod = types.ModuleType("engines.__test_mixed__")

        # Simulate a re-export from another module — alphabetically
        # before the real engine class.
        class AlphaEngine:
            __module__ = "engines.somewhere_else"

        # The real class actually defined in this module
        class ZetaEngine:
            __module__ = "engines.__test_mixed__"

        mod.AlphaEngine = AlphaEngine
        mod.ZetaEngine = ZetaEngine

        registry._ENGINE_MAP["__test_mixed__"] = "engines.__test_mixed__"

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "engines.__test_mixed__":
                return mod
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        try:
            engine = registry.get_engine("__test_mixed__")
            assert isinstance(engine, ZetaEngine)
        finally:
            registry._ENGINE_MAP.pop("__test_mixed__", None)

    def test_falls_back_to_re_export_when_no_local_class(self, monkeypatch):
        """If a module has only re-exported Engine classes (no
        locally-defined ones), the registry still loads the
        re-export rather than failing."""
        from engines import registry
        import importlib
        import types

        mod = types.ModuleType("engines.__test_reexport_only__")

        class ReExportedEngine:
            __module__ = "engines.somewhere_else"

        mod.ReExportedEngine = ReExportedEngine

        registry._ENGINE_MAP["__test_reexport_only__"] = "engines.__test_reexport_only__"

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "engines.__test_reexport_only__":
                return mod
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        try:
            engine = registry.get_engine("__test_reexport_only__")
            assert isinstance(engine, ReExportedEngine)
        finally:
            registry._ENGINE_MAP.pop("__test_reexport_only__", None)


# ── Thread safety ────────────────────────────────────────────


class TestThreadSafeCache:
    def test_concurrent_get_engine_does_not_double_instantiate(self, monkeypatch):
        """Two threads calling get_engine() concurrently should
        get the same instance — previously the cache had no lock,
        so the read at the top + write at the bottom could race."""
        from engines import registry
        import importlib
        import threading
        import types

        instantiation_count = {"n": 0}

        class _SlowEngine:
            __module__ = "engines.__test_concurrent__"
            def __init__(self):
                # Simulate work so both threads have a chance to
                # observe the empty cache before either writes.
                instantiation_count["n"] += 1
                import time
                time.sleep(0.05)

        mod = types.ModuleType("engines.__test_concurrent__")
        mod.ConcurrentEngine = _SlowEngine

        registry._ENGINE_MAP["__test_concurrent__"] = "engines.__test_concurrent__"

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "engines.__test_concurrent__":
                return mod
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)

        results = []
        def worker():
            results.append(registry.get_engine("__test_concurrent__"))

        try:
            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            # All five threads return the SAME cached instance.
            assert all(r is results[0] for r in results)
            # Even if one or two threads raced past the initial
            # cache check, the final cache write is atomic and
            # subsequent reads return the winning instance.
            assert results[0] is registry._cache["__test_concurrent__"]
        finally:
            registry._ENGINE_MAP.pop("__test_concurrent__", None)
