"""Wave 8 observability improvements.

Covers four changes:

  1. Controller: ~10 silent ``except Exception: pass`` blocks replaced
     with ``_record(phase, exc)`` so failures surface in cycle_result.
  2. Adapter metrics: ``_feed_sla_tracker`` made fail-soft internally.
  3. UnifiedMemory: new ``get_init_status()`` for operator dashboards.
  4. AIReasoning: bare ``except Exception: pass`` → ``logger.debug``.
"""
from __future__ import annotations

import ast
import inspect
import logging
import textwrap
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ===================================================================
# 1. Controller: silent-except → _record() for new phases
# ===================================================================


class TestControllerNewRecordPhases:
    """Wave 8 promoted ~10 additional ``except Exception: pass`` blocks
    to ``_record(phase_name, exc)``. Verify the phase names are wired."""

    WAVE8_PHASES = [
        "working_memory_clear",
        "exploration_boost",
        "exploration_record",
        "working_memory_store",
        "engine_memory_mirror",
        "memory_maintenance",
        "product_performance",
        "dashboard_generate",
        "structured_log",
        "cycle_reporter",
        "notifications",
    ]

    def test_all_wave8_phase_names_in_run_cycle_source(self):
        """Every Wave 8 phase name appears as a ``_record(...)``
        argument in the cycle body.

        Post-PR #244 the body lives in ``_run_cycle_internal``;
        the public ``run_cycle`` is the active-store wrapper.
        """
        from core.autonomous.controller import AutonomousController

        src = inspect.getsource(
            AutonomousController._run_cycle_internal,
        )
        for phase in self.WAVE8_PHASES:
            assert f'_record("{phase}"' in src, (
                f"phase {phase!r} not wired to _record() in "
                "_run_cycle_internal"
            )

    def test_no_bare_except_pass_in_run_cycle(self):
        """AST check: cycle body must not contain any bare
        ``except Exception: pass`` handlers (the pre-Wave-8 pattern)."""
        from core.autonomous.controller import AutonomousController

        source = textwrap.dedent(
            inspect.getsource(
                AutonomousController._run_cycle_internal,
            ),
        )
        tree = ast.parse(source)

        bare_passes: list[int] = []

        class _Visitor(ast.NodeVisitor):
            def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
                # Pattern: except Exception: pass (no 'as' binding)
                if (
                    node.name is None
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)
                ):
                    bare_passes.append(node.lineno)
                self.generic_visit(node)

        _Visitor().visit(tree)
        assert not bare_passes, (
            f"_run_cycle_internal still has {len(bare_passes)} "
            f"bare 'except: pass' handlers at relative lines "
            f"{bare_passes}"
        )

    def test_record_helper_defined_before_first_use(self):
        """``_record`` must be defined before the working_memory_clear
        block (the first user of _record in the cycle)."""
        from core.autonomous.controller import AutonomousController

        src = inspect.getsource(
            AutonomousController._run_cycle_internal,
        )
        record_pos = src.index("def _record(")
        first_use = src.index('_record("working_memory_clear"')
        assert record_pos < first_use


# ===================================================================
# 2. Adapter metrics: _feed_sla_tracker fail-soft
# ===================================================================


class TestFeedSlaTrackerFailSoft:
    """``_feed_sla_tracker`` should absorb exceptions internally
    rather than letting them propagate to the outer record() caller."""

    def test_import_error_does_not_propagate(self):
        from core.adapters.metrics import AdapterMetricsCollector

        collector = AdapterMetricsCollector()
        # Break the import path so _feed_sla_tracker hits ImportError
        with patch.dict("sys.modules", {"core.telemetry.metrics_collector": None}):
            # Should NOT raise
            collector._feed_sla_tracker(
                adapter="test", success=True, latency_ms=10.0, cost=0.0,
            )

    def test_tracker_crash_does_not_propagate(self):
        from core.adapters.metrics import AdapterMetricsCollector

        collector = AdapterMetricsCollector()

        with patch(
            "core.telemetry.metrics_collector.MetricsCollector"
        ) as mock_cls:
            mock_cls.return_value.get_sla_tracker.return_value.record.side_effect = (
                RuntimeError("boom")
            )
            # Should NOT raise
            collector._feed_sla_tracker(
                adapter="test", success=True, latency_ms=10.0, cost=0.0,
            )

    def test_record_still_captures_adapter_stats_on_sla_crash(self):
        """The outer record() must complete even when _feed_sla_tracker
        explodes internally."""
        from core.adapters.metrics import AdapterMetricsCollector

        collector = AdapterMetricsCollector()

        def _boom(**kw):
            raise RuntimeError("sla down")

        collector._feed_sla_tracker = _boom  # type: ignore[assignment]
        collector.record("openai", success=True, latency_ms=100.0)
        stats = collector.stats_for("openai")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1

    def test_feed_sla_tracker_has_internal_try_except(self):
        """Source-level check that _feed_sla_tracker wraps its body
        in try/except (not relying on the caller to catch)."""
        from core.adapters.metrics import AdapterMetricsCollector

        src = inspect.getsource(AdapterMetricsCollector._feed_sla_tracker)
        assert "try:" in src
        assert "except Exception" in src
        assert "logger.debug" in src


# ===================================================================
# 3. UnifiedMemory: get_init_status()
# ===================================================================


class TestUnifiedMemoryGetInitStatus:
    """``get_init_status()`` exposes structured health info
    for operator dashboards."""

    def test_not_initialized_status(self):
        from core.memory.unified_memory import UnifiedMemory

        um = UnifiedMemory()
        status = um.get_init_status()
        assert status["status"] == "not_initialized"
        assert status["healthy"] == []
        assert status["failed"] == []
        assert status["errors"] == {}

    def test_ok_status_after_clean_init(self):
        from core.memory.unified_memory import UnifiedMemory

        um = UnifiedMemory()
        um.initialize()
        status = um.get_init_status()

        # Status is either "ok" (all backends loaded) or "degraded"
        # (some failed — expected in test env without all deps).
        assert status["status"] in ("ok", "degraded")
        assert isinstance(status["healthy"], list)
        assert isinstance(status["failed"], list)
        assert isinstance(status["errors"], dict)
        # Every failed backend has an error message
        for name in status["failed"]:
            assert name in status["errors"]
            assert len(status["errors"][name]) > 0

    def test_degraded_status_with_failures(self):
        from core.memory.unified_memory import UnifiedMemory

        um = UnifiedMemory()
        um._initialized = True
        um._init_errors = {"brain_memory": "ImportError: no module"}
        status = um.get_init_status()

        assert status["status"] == "degraded"
        assert "brain_memory" in status["failed"]
        assert "brain_memory" not in status["healthy"]
        assert status["errors"]["brain_memory"] == "ImportError: no module"

    def test_healthy_and_failed_are_disjoint(self):
        from core.memory.unified_memory import UnifiedMemory

        um = UnifiedMemory()
        um._initialized = True
        um._init_errors = {
            "experience": "ModuleNotFoundError: x",
            "persistent": "OSError: disk full",
        }
        status = um.get_init_status()

        healthy_set = set(status["healthy"])
        failed_set = set(status["failed"])
        assert healthy_set.isdisjoint(failed_set)
        assert "experience" in failed_set
        assert "persistent" in failed_set

    def test_all_backends_accounted_for(self):
        """Every expected backend appears in either healthy or failed."""
        from core.memory.unified_memory import UnifiedMemory

        um = UnifiedMemory()
        um._initialized = True
        um._init_errors = {}
        status = um.get_init_status()

        expected = {
            "shared_memory", "brain_memory", "experience",
            "cross_cache", "persistent", "data_architecture",
            "memory_intelligence", "intelligence_cycle",
        }
        actual = set(status["healthy"]) | set(status["failed"])
        assert actual == expected

    def test_get_init_errors_still_works(self):
        """Existing ``get_init_errors()`` is not broken by the new method."""
        from core.memory.unified_memory import UnifiedMemory

        um = UnifiedMemory()
        um._init_errors = {"x": "err"}
        errors = um.get_init_errors()
        assert errors == {"x": "err"}
        # Returns a copy
        errors["y"] = "other"
        assert "y" not in um._init_errors


# ===================================================================
# 4. AIReasoning: bare except → logger.debug
# ===================================================================


class TestReasoningLogging:
    """AIReasoning._get_router and is_llm_available now log
    failures instead of silently passing."""

    def test_get_router_no_bare_pass(self):
        from core.ai.reasoning import AIReasoning

        src = inspect.getsource(AIReasoning._get_router)
        # Should have logger.debug, not bare pass
        assert "logger.debug" in src
        # The except block should NOT be just 'pass'
        tree = ast.parse(textwrap.dedent(src))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    pytest.fail("_get_router still has bare except:pass")

    def test_is_llm_available_no_bare_pass(self):
        from core.ai.reasoning import AIReasoning

        src = inspect.getsource(AIReasoning.is_llm_available)
        assert "logger.debug" in src
        tree = ast.parse(textwrap.dedent(src))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    pytest.fail("is_llm_available still has bare except:pass")

    def test_get_router_failure_logs_at_debug(self, caplog):
        """When ModelRouter import fails, we see a DEBUG log."""
        from core.ai.reasoning import AIReasoning
        from utils.logger import get_logger

        r = AIReasoning()
        r._router = None

        # The shopai logger has propagate=False, so caplog (which
        # attaches to root) won't see it. Temporarily enable
        # propagation for the test.
        lg = get_logger("ai.reasoning")
        orig_propagate = lg.propagate
        lg.propagate = True
        try:
            with patch.dict("sys.modules", {"models.routing.model_router": None}):
                with caplog.at_level(logging.DEBUG, logger="shopai.ai.reasoning"):
                    result = r._get_router()
        finally:
            lg.propagate = orig_propagate

        assert result is None
        debug_msgs = [
            rec.message for rec in caplog.records
            if rec.levelno == logging.DEBUG
        ]
        assert any("ModelRouter" in m for m in debug_msgs), (
            f"Expected ModelRouter debug log, got: {debug_msgs}"
        )

    def test_is_llm_available_failure_logs_at_debug(self, caplog):
        """When Ollama is unreachable, we see a DEBUG log."""
        from core.ai.reasoning import AIReasoning
        from utils.logger import get_logger

        r = AIReasoning()
        r._available = None
        r._ollama_url = "http://localhost:99999"  # unreachable

        lg = get_logger("ai.reasoning")
        orig_propagate = lg.propagate
        lg.propagate = True
        try:
            with caplog.at_level(logging.DEBUG, logger="shopai.ai.reasoning"):
                result = r.is_llm_available()
        finally:
            lg.propagate = orig_propagate

        assert result is False
        debug_msgs = [
            rec.message for rec in caplog.records
            if rec.levelno == logging.DEBUG
        ]
        assert any("Ollama" in m for m in debug_msgs), (
            f"Expected Ollama debug log, got: {debug_msgs}"
        )
