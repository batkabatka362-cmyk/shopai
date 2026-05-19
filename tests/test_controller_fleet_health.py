"""Tests for ``_compute_fleet_health`` -- the autonomous
controller's Phase 0.5 fleet-health rollup.

Lives at module level (see ``core.autonomous.controller``) so
the autonomous loop can call it once per cycle, observability
dashboards see the trajectory across cycles, and tests can
exercise it without spinning up the full controller.

Coverage:

  1. Verdict counts populate correctly across mixed verdicts.
  2. ``unhealthy_engines`` lists names sorted alphabetically.
  3. WARNING log fires when at least one engine is unhealthy.
  4. Empty roster handled (scored=0, no warning).
  5. Per-engine score_engine raise is skipped; siblings score.
  6. ImportError fails open with ``error`` in result.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

from core.autonomous.controller import _compute_fleet_health


def _stub_health(engine: str, verdict: str, score: int = 8):
    from core.approval.engine_health import EngineHealth
    return EngineHealth(
        engine=engine, score=score, verdict=verdict,
        signals={}, concerns=[],
    )


class TestVerdictCounts:

    def test_mixed_verdicts_counted(self):
        verdicts = {
            "loyalty": "unhealthy",
            "cart_recovery": "warning",
            "discount_strategy": "healthy",
        }
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            {k: "maximize_profit" for k in verdicts},
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            side_effect=lambda engine, **kw: _stub_health(
                engine, verdicts[engine],
            ),
        ):
            result = _compute_fleet_health()
        assert result["verdict_counts"] == {
            "healthy": 1, "warning": 1, "unhealthy": 1,
        }
        assert result["scored"] == 3

    def test_all_healthy(self):
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            {"loyalty": "g", "cart_recovery": "g"},
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            return_value=_stub_health("loyalty", "healthy"),
        ):
            result = _compute_fleet_health()
        assert result["verdict_counts"]["healthy"] == 2
        assert result["verdict_counts"]["unhealthy"] == 0
        assert result["unhealthy_engines"] == []

    def test_empty_roster(self):
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            {}, clear=True,
        ):
            result = _compute_fleet_health()
        assert result["scored"] == 0
        assert result["unhealthy_engines"] == []


class TestUnhealthyList:

    def test_lists_sorted(self):
        verdicts = {
            "z_engine": "unhealthy",
            "a_engine": "unhealthy",
            "m_engine": "healthy",
        }
        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            {k: "g" for k in verdicts},
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            side_effect=lambda engine, **kw: _stub_health(
                engine, verdicts[engine],
            ),
        ):
            result = _compute_fleet_health()
        assert result["unhealthy_engines"] == [
            "a_engine", "z_engine",
        ]


class _ListHandler(logging.Handler):
    """Capture records directly on the controller's logger.
    The configured logger has ``propagate=False`` so caplog's
    root-level capture misses it -- attaching a handler here
    is the simplest workaround."""
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


class TestWarningLog:

    def _capture_warnings(self):
        from core.autonomous import controller as ctrl_mod
        handler = _ListHandler()
        handler.setLevel(logging.WARNING)
        ctrl_mod.logger.addHandler(handler)
        return handler, ctrl_mod.logger

    def test_warning_fires_when_unhealthy(self):
        handler, logger_obj = self._capture_warnings()
        try:
            verdicts = {"loyalty": "unhealthy"}
            with patch.dict(
                "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
                {k: "g" for k in verdicts},
                clear=True,
            ), patch(
                "core.approval.engine_health.score_engine",
                side_effect=lambda engine, **kw: _stub_health(
                    engine, verdicts[engine],
                ),
            ):
                _compute_fleet_health()
        finally:
            logger_obj.removeHandler(handler)
        warnings = [
            r for r in handler.records
            if r.levelname == "WARNING"
            and "fleet_health" in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "1 unhealthy" in warnings[0].getMessage()
        assert "loyalty" in warnings[0].getMessage()

    def test_no_warning_when_all_healthy(self):
        handler, logger_obj = self._capture_warnings()
        try:
            with patch.dict(
                "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
                {"loyalty": "g"},
                clear=True,
            ), patch(
                "core.approval.engine_health.score_engine",
                return_value=_stub_health("loyalty", "healthy"),
            ):
                _compute_fleet_health()
        finally:
            logger_obj.removeHandler(handler)
        warnings = [
            r for r in handler.records
            if r.levelname == "WARNING"
            and "fleet_health" in r.getMessage()
        ]
        assert warnings == []


class TestSourceFailureIsolation:

    def test_per_engine_raise_skipped(self):
        def _score(engine, **kw):
            if engine == "broken":
                raise RuntimeError("score down")
            return _stub_health(engine, "healthy")

        with patch.dict(
            "core.goals.engine_goal_map.ENGINE_GOAL_MAP",
            {"broken": "g", "loyalty": "g"},
            clear=True,
        ), patch(
            "core.approval.engine_health.score_engine",
            side_effect=_score,
        ):
            result = _compute_fleet_health()
        # broken skipped; loyalty scored
        assert result["scored"] == 1
        assert result["verdict_counts"]["healthy"] == 1

    def test_import_failure_returns_error(self):
        # Inject ImportError at the score_engine attribute so
        # the helper's try/except triggers.
        with patch(
            "core.approval.engine_health.score_engine",
            side_effect=ImportError("module gone"),
        ):
            result = _compute_fleet_health()
        # Per-engine ImportError is caught at the per-engine
        # level (still scored=0); we don't crash. The 'error'
        # field is reserved for the top-level import failure
        # path; this path leaves scored=0 without error key.
        assert result["scored"] == 0

    def test_top_level_import_failure(self):
        """When the engine_health module itself fails to
        import, the helper returns an error envelope."""
        with patch(
            "core.autonomous.controller._compute_fleet_health",
            wraps=_compute_fleet_health,
        ):
            # Force the engine_goal_map import to raise via a
            # builtin import patch -- this exercises the module-
            # level try/except in _compute_fleet_health.
            import builtins
            real_import = builtins.__import__

            def _raise(name, *a, **kw):
                if name == "core.approval.engine_health":
                    raise ImportError("engine_health missing")
                return real_import(name, *a, **kw)

            with patch("builtins.__import__", side_effect=_raise):
                result = _compute_fleet_health()
        assert "error" in result
        assert result["scored"] == 0
