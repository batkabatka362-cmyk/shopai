"""Tests for audit-pass-8 fixes in MainOrchestrator.

  1. _wire_executors() wrapped all 5 executor imports in a single
     try/except, so one missing import disabled all 5.
  2. submit_task() mutated the cached response dict in place,
     leaking the previous caller's _cached flag and elapsed_seconds
     into every subsequent reader of the same entry.
  3. Three silent `except Exception: pass` blocks in submit_task
     hid engine_mem and kpi_tracker failures from operators.
  4. submit_task() and _execute_with_fallback() used direct
     `result["status"]` access — a malformed executor response
     missing that key would crash the orchestrator mid-cycle.
"""
import pytest


# ── _wire_executors per-executor isolation ───────────────────


class TestWireExecutorsIsolation:
    def test_one_broken_import_does_not_disable_others(self, monkeypatch):
        """Regression: previously a single tuple of imports meant
        one missing executor killed all five. Now each executor
        loads independently."""
        from core.orchestrator.main_orchestrator import MainOrchestrator

        mo = MainOrchestrator()

        registered: list[tuple[str, str]] = []
        failures: list[str] = []

        class _StubBridge:
            def register_executor(self, provider, action, executor):
                registered.append((provider, action))

        mo._execution_bridge = _StubBridge()

        import importlib
        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "execution.marketing.ad_launcher":
                raise ImportError("AdLauncher missing in test env")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)

        # Capture warnings via direct logger patch
        import core.orchestrator.main_orchestrator as mo_mod
        warnings: list[str] = []
        monkeypatch.setattr(
            mo_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )
        # Other executors may or may not import in this env, but
        # at minimum we verify the AdLauncher failure is captured
        # and doesn't blow up the whole call.
        mo._wire_executors()
        assert any("AdLauncher" in w for w in warnings)

    def test_all_broken_does_not_crash(self, monkeypatch):
        from core.orchestrator.main_orchestrator import MainOrchestrator
        import core.orchestrator.main_orchestrator as mo_mod
        import importlib

        mo = MainOrchestrator()

        class _StubBridge:
            def register_executor(self, *a, **k):
                pass

        mo._execution_bridge = _StubBridge()

        def fake_import(name, *args, **kwargs):
            if name.startswith("execution."):
                raise ImportError(f"all broken: {name}")
            return importlib.__import__(name, *args, **kwargs)

        # Use the actual module's importlib reference
        monkeypatch.setattr(
            mo_mod, "importlib", type("M", (), {"import_module": fake_import}),
            raising=False,
        )
        # The above monkeypatch doesn't work for inline imports — use
        # importlib's real import_module patch instead.
        real = importlib.import_module
        monkeypatch.setattr(importlib, "import_module", lambda name, *a, **k:
                            (_ for _ in ()).throw(ImportError("nope"))
                            if name.startswith("execution.")
                            else real(name, *a, **k))

        warnings: list[str] = []
        monkeypatch.setattr(
            mo_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        # Should not raise
        mo._wire_executors()
        # 5 per-executor warnings + 1 summary warning
        assert sum("failed to wire" in w for w in warnings) == 5


# ── Cached entry mutation isolation ──────────────────────────


class TestCachedResponseIsolation:
    def test_cache_hit_does_not_mutate_stored_entry(self, monkeypatch):
        """Regression: cached["_cached"] = True mutated the cached
        dict in place. The next cache hit would see _cached already
        True and inherit the previous caller's elapsed_seconds."""
        from core.orchestrator.main_orchestrator import MainOrchestrator

        mo = MainOrchestrator()
        mo._running = True

        # Stub the cache to always return the same dict object
        original_dict = {"task_id": "x", "status": "completed", "result": {"v": 1}}

        class _StubCache:
            def __init__(self):
                self._d = original_dict
            def get(self, *a, **k):
                return self._d
            def store(self, *a, **k):
                pass
            def get_stats(self):
                return {}

        mo._exec_cache = _StubCache()

        # Stub other touched modules so submit_task can return early
        class _Stub:
            def increment(self, *a, **k): pass
            def histogram(self, *a, **k): pass
            def snapshot(self, *a, **k): return {}
            def start_trace(self, *a, **k): return type("S", (), {"trace_id": "t", "span_id": "s"})()
            def start_span(self, *a, **k): return type("S", (), {"trace_id": "t", "span_id": "s"})()
            def finish_span(self, *a, **k): pass
            def emit(self, *a, **k): pass
            def get_stats(self): return {}
        mo._metrics = _Stub()
        mo._tracer = _Stub()
        mo._event_bus = _Stub()

        result1 = mo.submit_task("x", {"a": 1})
        assert result1["_cached"] is True
        # The original dict in the cache must NOT have been
        # mutated — it stays clean for the next caller.
        assert "_cached" not in original_dict
        assert "elapsed_seconds" not in original_dict

    def test_two_callers_get_independent_responses(self, monkeypatch):
        from core.orchestrator.main_orchestrator import MainOrchestrator

        mo = MainOrchestrator()
        mo._running = True
        cached_value = {"task_id": "y", "status": "completed", "result": {}}

        class _StubCache:
            def get(self, *a, **k): return cached_value
            def store(self, *a, **k): pass
            def get_stats(self): return {}

        class _Stub:
            def increment(self, *a, **k): pass
            def histogram(self, *a, **k): pass
            def snapshot(self, *a, **k): return {}
            def start_trace(self, *a, **k): return type("S", (), {"trace_id": "t", "span_id": "s"})()
            def start_span(self, *a, **k): return type("S", (), {"trace_id": "t", "span_id": "s"})()
            def finish_span(self, *a, **k): pass
            def emit(self, *a, **k): pass
            def get_stats(self): return {}

        mo._exec_cache = _StubCache()
        mo._metrics = _Stub()
        mo._tracer = _Stub()
        mo._event_bus = _Stub()

        r1 = mo.submit_task("y")
        r2 = mo.submit_task("y")
        # Both responses are flagged as cached
        assert r1["_cached"] is True
        assert r2["_cached"] is True
        # But mutating one doesn't affect the other or the source
        r1["mutated"] = "yes"
        assert "mutated" not in r2
        assert "mutated" not in cached_value


# ── _execute_with_fallback defensive .get("status") ──────────


class TestExecuteWithFallbackDefensive:
    def test_missing_status_key_does_not_crash(self):
        from core.orchestrator.main_orchestrator import MainOrchestrator

        mo = MainOrchestrator()

        class _Router:
            def __init__(self):
                self.calls = 0
            def execute(self, *a, **k):
                self.calls += 1
                # Malformed response: no "status" key
                return {"result": "weird", "no_status_key": True}

        mo._execution_router = _Router()

        class _Fallback:
            def get_fallback(self, engine, attempt):
                return None
        mo._fallback_router = _Fallback()
        mo._config = {}

        # Should not raise — returns the malformed dict
        result = mo._execute_with_fallback("engine", "task1", {})
        assert isinstance(result, dict)

    def test_none_response_is_normalized(self):
        from core.orchestrator.main_orchestrator import MainOrchestrator

        mo = MainOrchestrator()

        class _Router:
            def execute(self, *a, **k):
                return None

        class _Fallback:
            def get_fallback(self, engine, attempt):
                return None

        mo._execution_router = _Router()
        mo._fallback_router = _Fallback()
        mo._config = {}

        # When everything returns None, the function now returns a
        # synthesized failed dict instead of returning None and
        # crashing the caller's `result["status"]` access.
        result = mo._execute_with_fallback("engine", "task1", {})
        assert result["status"] == "failed"
        assert "no result" in result["error"]
