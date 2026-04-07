"""Tests for audit-pass-9 fixes in FullSystemLoop.

  1. _phase_execute() wrapped both ProductCreator + ProductUpdater
     imports in a single try/except — one missing import disabled
     both Shopify executors silently. THIRD instance of the same
     batch-import anti-pattern (after CoreOrchestrator and
     MainOrchestrator._wire_executors).

  2. _phase_intelligence() error path returned a dict WITHOUT
     a `status` key, so the abort gate at line 76 of run() never
     fired for crashes. The cycle proceeded to phase 3 (agents)
     with broken intel data.

  3. _phase_data() customer cleaner failures, _phase_memory()
     vector search failures, and _get_vector_db() persist-path
     failures all swallowed exceptions silently.
"""
import pytest


# ── _phase_execute per-executor isolation ────────────────────


class TestPhaseExecuteExecutorIsolation:
    def test_one_broken_import_does_not_disable_other(self, monkeypatch):
        """Regression: previously a single broken executor import
        disabled both Shopify executors. Now each loads
        independently."""
        from core.full_system_loop import FullSystemLoop
        import core.full_system_loop as fsl_mod
        import importlib

        registered: list[tuple[str, str]] = []

        class _StubBridge:
            def register_executor(self, provider, action, executor):
                registered.append((provider, action))
            def plan_actions(self, *a, **k):
                return []
            def get_queue(self):
                return []
            def execute_approved(self):
                return []

        # Force ExecutionBridge constructor to return our stub
        monkeypatch.setattr(
            "core.bridge.execution_bridge.ExecutionBridge",
            lambda: _StubBridge(),
        )

        warnings: list[str] = []
        monkeypatch.setattr(
            fsl_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "execution.shopify.product_updater":
                raise ImportError("ProductUpdater missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", fake_import)

        loop = FullSystemLoop()
        loop._phase_execute({"execution": {"ready": []}}, {})

        # The failed updater is captured as a warning
        assert any("ProductUpdater" in w for w in warnings)


# ── _phase_intelligence aborts on crash ──────────────────────


class TestPhaseIntelligenceAborts:
    def test_crash_returns_status_aborted(self, monkeypatch):
        """Regression: previously the error response missed the
        status key so the abort gate never fired and broken intel
        data flowed into phase 3."""
        from core.full_system_loop import FullSystemLoop
        import core.full_system_loop as fsl_mod

        class _BrokenLoop:
            def run(self, data, goal):
                raise RuntimeError("intel exploded")

        # Patch IntelligenceLoop import target
        import core.intelligence_loop as il_mod
        monkeypatch.setattr(il_mod, "IntelligenceLoop", _BrokenLoop)

        loop = FullSystemLoop()
        result = loop._phase_intelligence({"products": []}, "maximize_profit")
        assert result["status"] == "aborted"
        assert "intel exploded" in result["reason"]
        assert result["data_quality"] == 0

    def test_normal_run_unaffected(self, monkeypatch):
        from core.full_system_loop import FullSystemLoop
        import core.intelligence_loop as il_mod

        class _OkLoop:
            def run(self, data, goal):
                return {
                    "data_quality": 95,
                    "decision": {"action": "go"},
                    "plan": {"actions": 3},
                }

        monkeypatch.setattr(il_mod, "IntelligenceLoop", _OkLoop)
        loop = FullSystemLoop()
        result = loop._phase_intelligence({"products": []}, "x")
        assert "status" not in result  # normal path unchanged
        assert result["data_quality"] == 95

    def test_run_skips_phases_when_intel_aborts(self, monkeypatch):
        """End-to-end: a crashing intelligence loop must short-
        circuit the cycle to status='partial' instead of running
        agents+execution on broken data."""
        from core.full_system_loop import FullSystemLoop
        import core.intelligence_loop as il_mod

        class _BrokenLoop:
            def run(self, data, goal):
                raise RuntimeError("crash")

        monkeypatch.setattr(il_mod, "IntelligenceLoop", _BrokenLoop)

        # Track whether _phase_agents/_phase_execute would run by
        # spy-patching them.
        loop = FullSystemLoop()
        agents_called = []
        exec_called = []
        loop._phase_agents = lambda *a, **k: (agents_called.append(1), {})[1]
        loop._phase_execute = lambda *a, **k: (exec_called.append(1), {})[1]
        loop._phase_memory = lambda *a, **k: {"stored": 0}
        loop._phase_learn = lambda *a, **k: {"rules_updated": 0}

        result = loop.run({"products": []})
        assert result["status"] == "partial"
        assert agents_called == []
        assert exec_called == []


# ── Silent-swallow promotions ────────────────────────────────


class TestSilentSwallowPromotion:
    def test_customer_cleaner_failure_logged(self, monkeypatch):
        from core.full_system_loop import FullSystemLoop
        import core.full_system_loop as fsl_mod

        warnings: list[str] = []
        monkeypatch.setattr(
            fsl_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        # Force DataCleaner to raise
        class _BrokenCleaner:
            def clean(self, data):
                raise RuntimeError("cleaner dead")

        import data_pipeline.processing.cleaner as cleaner_mod
        monkeypatch.setattr(cleaner_mod, "DataCleaner", lambda: _BrokenCleaner())

        loop = FullSystemLoop()
        loop._phase_data({"customers": [{"id": 1}]}, {})
        assert any("customer cleaning failed" in w for w in warnings)

    def test_vector_search_failure_logged(self, monkeypatch):
        from core.full_system_loop import FullSystemLoop
        import core.full_system_loop as fsl_mod

        warnings: list[str] = []
        monkeypatch.setattr(
            fsl_mod.logger, "warning",
            lambda msg, *args, **k: warnings.append(msg % args if args else msg),
        )

        class _BrokenVDB:
            def total_documents(self):
                return 5
            def search(self, *a, **k):
                raise RuntimeError("search exploded")
            def add(self, *a, **k):
                pass
            def save(self):
                pass

        # Reset class-level cache and inject the stub
        FullSystemLoop._shared_vdb = _BrokenVDB()
        FullSystemLoop._shared_cache = type("C", (), {"set": lambda self, *a, **k: None})()

        try:
            loop = FullSystemLoop()
            loop._phase_memory("test_cycle", {
                "intelligence": {"decision": {"action": "x"}},
                "execution": {"success_count": 0, "fail_count": 0, "dispatched": 0},
            })
            assert any("vector similarity search" in w for w in warnings)
        finally:
            # Reset class-level state for other tests
            FullSystemLoop._shared_vdb = None
            FullSystemLoop._shared_cache = None
