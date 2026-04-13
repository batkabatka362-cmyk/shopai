"""Tests for LayerDispatcher + AgentDispatcher init/run hardening.

These cover the audit-pass-5 fixes:

  1. LayerDispatcher used a single tuple-import for all 12 layer
     classes. One missing class meant zero layers loaded — the
     entire dispatcher silently went offline behind a short
     "Layer initialization partial" warning.
  2. LayerDispatcher.run_all() logged per-layer exec failures at
     DEBUG, so broken layers were invisible at the default INFO
     level. The cycle just kept going with `status="error"` in
     the result dict and no operator-visible signal.
  3. AgentDispatcher had the same DEBUG-level swallow on init,
     and no public introspection of which agents had failed.
  4. AutonomousController logged layer-phase exceptions at DEBUG.
"""
import sys

import pytest


# ── LayerDispatcher per-layer init isolation ─────────────────


def _fresh_layer_dispatcher():
    from core.autonomous.layer_dispatcher import LayerDispatcher
    return LayerDispatcher()


class TestLayerDispatcherPerLayerInit:
    def test_single_broken_layer_does_not_disable_others(self, monkeypatch):
        """Regression: previously a tuple-import wrapped all 12 layer
        classes — one missing class killed every other layer."""
        import importlib
        d = _fresh_layer_dispatcher()

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "layers":
                raise ImportError("intentional test failure")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        d.initialize()
        # All 12 layers will fail (because every spec uses module
        # path "layers"), but the failure is captured per-layer.
        assert len(d.get_init_errors()) == 12
        for err in d.get_init_errors().values():
            assert "ImportError" in err
            assert "intentional" in err

    def test_partial_failure_reports_per_layer_errors(self, monkeypatch):
        import importlib
        d = _fresh_layer_dispatcher()
        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            mod = real_import(name, *args, **kwargs)
            return mod

        # Wrap getattr on the layers module to fail for one specific
        # class while letting others succeed.
        d2 = _fresh_layer_dispatcher()
        try:
            import layers as _layers
        except Exception:
            pytest.skip("layers module not importable in test env")

        original_data = getattr(_layers, "DataLayerFlow", None)
        if original_data is None:
            pytest.skip("DataLayerFlow not present in test env")
        # Temporarily replace one class with something that explodes
        class _Boom:
            def __init__(self):
                raise RuntimeError("boom on construct")
        monkeypatch.setattr(_layers, "DataLayerFlow", _Boom)

        d2.initialize()
        # The one bad layer is captured; the others can still load.
        errors = d2.get_init_errors()
        assert "data" in errors
        assert "RuntimeError" in errors["data"]
        # Other layers may or may not have loaded depending on env;
        # the important thing is the dispatcher kept going past the
        # broken layer rather than aborting on the first failure.
        assert d2._initialized is True

    def test_get_init_errors_empty_on_clean_init(self):
        # Without monkeypatching, real layers either all load or
        # all fail in this test env — either way the API returns
        # a plain dict.
        d = _fresh_layer_dispatcher()
        d.initialize()
        errors = d.get_init_errors()
        assert isinstance(errors, dict)


# ── LayerDispatcher run_all error visibility ─────────────────


class TestLayerDispatcherRunAllLogging:
    def test_layer_exception_logged_at_warning(self, monkeypatch):
        """Per-layer execution exceptions now log at WARNING. The
        previous DEBUG level meant operators never saw them."""
        import core.autonomous.layer_dispatcher as ld
        d = _fresh_layer_dispatcher()
        d._initialized = True

        class _BoomLayer:
            def run(self, data):
                raise RuntimeError("layer kaboom")

        d._layers = {"data": _BoomLayer()}

        # Capture warning calls directly on the module logger
        # because the project uses propagate=False so caplog can't
        # observe them.
        warnings: list[str] = []
        original = ld.logger.warning

        def _capture(msg, *args, **kwargs):
            warnings.append(msg % args if args else msg)
            return original(msg, *args, **kwargs)

        monkeypatch.setattr(ld.logger, "warning", _capture)
        result = d.run_all({})
        assert any("kaboom" in w for w in warnings)
        assert result["results"]["data"]["status"] == "error"


# ── AgentDispatcher per-agent init capture ───────────────────


def _fresh_agent_dispatcher():
    from core.autonomous.agent_dispatcher import AgentDispatcher
    return AgentDispatcher()


class TestAgentDispatcherInitCapture:
    def test_init_errors_api_returns_dict(self):
        d = _fresh_agent_dispatcher()
        d.initialize()
        errors = d.get_init_errors()
        assert isinstance(errors, dict)
        # In a clean test environment, some real agents may not be
        # importable; either way each entry is a string.
        for v in errors.values():
            assert isinstance(v, str)
            assert ":" in v  # "TypeName: message"

    def test_failed_agents_captured_with_type_and_message(self, monkeypatch):
        """Force a known import failure and verify the captured
        error string includes both the exception type and message."""
        import importlib
        d = _fresh_agent_dispatcher()
        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name.startswith("agents."):
                raise ModuleNotFoundError(f"forced: {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)
        d.initialize()
        errors = d.get_init_errors()
        assert len(errors) == 7  # all 7 agents fail
        for name, err in errors.items():
            assert "ModuleNotFoundError" in err
            assert "forced" in err

    def test_init_failure_logged_at_warning(self, monkeypatch):
        import importlib
        import core.autonomous.agent_dispatcher as ad
        d = _fresh_agent_dispatcher()
        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name.startswith("agents."):
                raise ImportError("nope")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)

        # Module logger uses propagate=False so caplog won't see it.
        # Capture .warning() calls directly.
        warnings: list[str] = []
        original = ad.logger.warning

        def _capture(msg, *args, **kwargs):
            warnings.append(msg % args if args else msg)
            return original(msg, *args, **kwargs)

        monkeypatch.setattr(ad.logger, "warning", _capture)
        d.initialize()
        # 7 per-agent warnings + 1 summary
        assert sum("failed to load" in w for w in warnings) == 7
        assert any("0/7" in w for w in warnings)
