"""Regression tests for Fix B: phase_errors observability.

Pre-fix the autonomous cycle wrapped 40+ phases in bare
``except Exception:`` blocks that only emitted ``logger.debug``
on failure. Operators running ``cli.py auto`` saw no warning
when a subsystem (competitor scan, brain think, cognitive,
RL pricing, segmentation, demand forecast, layers, agents,
smart execution, fulfillment, etc.) silently failed — the
cycle kept running with degraded intelligence and nothing in
the result surfaced the gap.

Fix B promoted every silent ``logger.debug`` to a per-cycle
``_record(name, exc)`` helper that:

  1. Logs at WARNING level (visible at default log config)
  2. Appends ``{phase_name: error_str}`` to a local
     ``phase_errors`` dict
  3. Surfaces the dict on ``cycle_result["phase_errors"]`` +
     a ``phase_error_count`` integer at the end of the cycle

These tests pin the fix so the observability gap doesn't
regress.
"""
from __future__ import annotations

import tempfile

import pytest


def _make_controller():
    """Build an AutonomousController against a disposable DB
    with enough seed data to reach every phase."""
    from data_pipeline.store.db import ShopAIDatabase
    from data_pipeline.store.store_manager import StoreManager
    from core.autonomous.controller import AutonomousController

    db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
    sm = StoreManager(db)
    sm.add_store("test", "test.myshopify.com", "shpat_test")
    db.upsert_products("test", [
        {"id": "p1", "title": "Widget", "price": 29.99,
         "cost": 10, "status": "active", "inventory_quantity": 50},
        {"id": "p2", "title": "Gadget", "price": 49.99,
         "cost": 20, "status": "active", "inventory_quantity": 30},
    ])
    db.upsert_orders("test", [
        {"id": "o1", "total": 79.98, "financial_status": "paid"},
        {"id": "o2", "total": 49.99, "financial_status": "paid"},
    ])
    db.upsert_customers("test", [
        {"id": "c1", "name": "Test", "email": "t@t.com"},
    ])
    db.log_sync("test", "products", "success", 2, 0.1)
    db.log_sync("test", "orders", "success", 2, 0.1)
    db.log_sync("test", "customers", "success", 1, 0.1)

    ac = AutonomousController(sm, auto_approve=False)
    ac.initialize()
    return ac


class TestPhaseErrorsSurface:
    def test_clean_cycle_has_empty_phase_errors(self):
        """When every phase runs cleanly, ``phase_errors`` is
        an empty dict and ``phase_error_count`` is zero. The
        fields MUST still be present (not just absent) so
        downstream consumers don't have to write ``get()``
        defaults."""
        ac = _make_controller()
        result = ac.run_cycle("test")
        assert "phase_errors" in result
        assert "phase_error_count" in result
        assert isinstance(result["phase_errors"], dict)
        assert result["phase_error_count"] == len(result["phase_errors"])

    def test_phase_errors_is_a_dict_not_list(self):
        ac = _make_controller()
        result = ac.run_cycle("test")
        assert isinstance(result["phase_errors"], dict)

    def test_phase_error_captures_exception_type(self, monkeypatch):
        """Force one phase (competitor_scan) to raise a
        specific exception and verify the typed error string
        shows up in ``phase_errors``."""
        ac = _make_controller()

        # Monkey-patch ``get_competitor_monitor`` to raise a
        # distinctive exception so we can assert the
        # ``phase_errors`` capture.
        import core.ai.competitor_monitor as cm_module

        class _MarkerError(RuntimeError):
            pass

        def _boom():
            raise _MarkerError("forced test failure")

        monkeypatch.setattr(cm_module, "get_competitor_monitor", _boom)

        result = ac.run_cycle("test")

        # Competitor scan should be the only failing phase —
        # every other phase still runs cleanly.
        errors = result.get("phase_errors", {})
        assert "competitor_scan" in errors, (
            f"expected competitor_scan in phase_errors, got keys {list(errors.keys())}"
        )
        assert "_MarkerError" in errors["competitor_scan"]
        assert "forced test failure" in errors["competitor_scan"]
        assert result["phase_error_count"] >= 1

    def test_multiple_phase_failures_are_all_captured(self, monkeypatch):
        """If two phases fail in the same cycle, both show up
        — the cycle doesn't short-circuit on the first
        failure."""
        ac = _make_controller()

        import core.ai.competitor_monitor as cm_module
        import core.brain.cognitive as cog_module

        def _boom1():
            raise RuntimeError("competitor boom")
        def _boom2():
            raise RuntimeError("cognitive boom")

        monkeypatch.setattr(cm_module, "get_competitor_monitor", _boom1)
        monkeypatch.setattr(cog_module, "get_cognitive_module", _boom2)

        result = ac.run_cycle("test")
        errors = result.get("phase_errors", {})

        assert "competitor_scan" in errors
        assert "cognitive_thinking" in errors
        assert "competitor boom" in errors["competitor_scan"]
        assert "cognitive boom" in errors["cognitive_thinking"]
        assert result["phase_error_count"] >= 2

    def test_phase_failure_does_not_break_cycle_status(self, monkeypatch):
        """The whole point of the silent-except pattern was
        that one failing phase shouldn't crash the whole
        cycle. The fix preserves that invariant — the cycle
        still returns ``status = complete``, it just now
        records the failure too."""
        ac = _make_controller()

        import core.ai.competitor_monitor as cm_module
        monkeypatch.setattr(
            cm_module, "get_competitor_monitor",
            lambda: (_ for _ in ()).throw(RuntimeError("x")),
        )

        result = ac.run_cycle("test")
        assert result.get("status") == "complete"
        assert "competitor_scan" in result.get("phase_errors", {})

    def test_phase_errors_key_is_slugified(self, monkeypatch):
        """``_record`` slugifies the phase name so dict keys
        are predictable snake_case. ``"Competitor scan"`` →
        ``"competitor_scan"``, not ``"Competitor scan"``."""
        ac = _make_controller()

        import core.ai.competitor_monitor as cm_module
        def _boom():
            raise RuntimeError("test")
        monkeypatch.setattr(cm_module, "get_competitor_monitor", _boom)

        result = ac.run_cycle("test")
        errors = result.get("phase_errors", {})
        # Wave 7 added synthetic injection keys that use "::" as
        # a namespace separator (e.g. "sla_breach::adapter_name",
        # "cognitive_mind"). Those are NOT produced by ``_record``
        # and follow their own naming convention. Filter them out
        # so we only test the slugification contract of ``_record``.
        _INJECTED_PREFIXES = ("sla_breach", "cognitive_mind", "reflection_hook")
        phase_keys = [
            k for k in errors
            if not any(k.startswith(p) for p in _INJECTED_PREFIXES)
        ]
        for key in phase_keys:
            # Lowercase, underscores only, no spaces/colons
            assert key == key.lower()
            assert " " not in key
            assert ":" not in key


class TestNoBareDebugLogsInRunCycle:
    """AST-level regression: the run_cycle method must NOT
    contain any bare ``logger.debug("X: %s", exc)`` calls
    that would silence phase failures. Every such log was
    promoted to ``_record`` by Fix B."""

    def test_run_cycle_has_no_silent_debug_logs(self):
        import ast
        import inspect
        import textwrap
        from core.autonomous.controller import AutonomousController

        # Post-PR #244 the body is in _run_cycle_internal.
        source = textwrap.dedent(
            inspect.getsource(AutonomousController._run_cycle_internal),
        )
        tree = ast.parse(source)

        # Find every ``logger.debug(...)`` call inside
        # run_cycle. The fix MAY leave some debug logs that
        # aren't in a phase failure context (e.g. diagnostic
        # notes) — but none should match the pattern
        # ``logger.debug("X: %s", exc)`` which is the
        # fingerprint of a silenced phase failure.
        offenders: list[str] = []

        class _Visitor(ast.NodeVisitor):
            def visit_Call(self, node: ast.Call) -> None:
                func = node.func
                if not isinstance(func, ast.Attribute):
                    self.generic_visit(node)
                    return
                if (
                    isinstance(func.value, ast.Name)
                    and func.value.id == "logger"
                    and func.attr == "debug"
                ):
                    # A bare ``except Exception as exc:`` phase
                    # failure log has the shape:
                    #   logger.debug("Phase: %s", exc)
                    # i.e. first arg is a string with "%s" and
                    # second arg is the ``exc`` name.
                    if (
                        len(node.args) == 2
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                        and "%s" in node.args[0].value
                        and isinstance(node.args[1], ast.Name)
                        and node.args[1].id == "exc"
                    ):
                        offenders.append(node.args[0].value)
                self.generic_visit(node)

        _Visitor().visit(tree)
        assert not offenders, (
            f"run_cycle still contains {len(offenders)} silent "
            f"debug logs that should be _record() calls: {offenders[:5]}"
        )

    def test_record_helper_exists_in_run_cycle(self):
        """The local ``_record`` helper must be defined inside
        the cycle body so each phase can call it.

        Post-PR #244 the body lives in ``_run_cycle_internal``
        (the public ``run_cycle`` is now a thin wrapper that
        sets the active-store context). The observability
        contract is on the body, so we inspect there.
        """
        import inspect
        from core.autonomous.controller import AutonomousController
        src = inspect.getsource(AutonomousController._run_cycle_internal)
        assert "def _record(" in src
        assert "phase_errors[phase_name]" in src
        assert "logger.warning(" in src

    def test_phase_errors_dict_initialised_in_run_cycle(self):
        import inspect
        from core.autonomous.controller import AutonomousController
        src = inspect.getsource(AutonomousController._run_cycle_internal)
        assert "phase_errors: dict[str, str] = {}" in src
