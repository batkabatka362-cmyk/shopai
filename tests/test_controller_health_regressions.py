"""Tests for ``_detect_regressions`` -- the controller's
Phase 0.6 regression detector.

Lives at module level (mirror of ``_compute_fleet_health``) so
the autonomous loop can call it once per cycle and tests can
exercise it without spinning up the full controller.

Coverage:
  1. Empty history returns empty rows.
  2. Flagged engines appear with full ``HealthRegression``
     fields flattened to a dict.
  3. WARNING log fires when any regression is flagged.
  4. ImportError fails open with an ``error`` field.
  5. find_regressions raise fails open with an ``error`` field.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

from core.autonomous.controller import _detect_regressions


def _stub_regression(
    *, engine="loyalty", latest_score=4,
    baseline_score=9.0, drop=5.0,
):
    from core.approval.engine_health_history import HealthRegression
    return HealthRegression(
        engine=engine,
        latest_score=latest_score,
        latest_verdict="unhealthy",
        baseline_score=baseline_score,
        drop=drop,
        samples_in_baseline=5,
    )


class _ListHandler(logging.Handler):
    """Capture records directly on the controller's logger;
    propagate=False blocks caplog's root-level capture."""
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


def _capture_warnings():
    from core.autonomous import controller as ctrl_mod
    handler = _ListHandler()
    handler.setLevel(logging.WARNING)
    ctrl_mod.logger.addHandler(handler)
    return handler, ctrl_mod.logger


class TestEmpty:

    def test_no_regressions_returns_empty(self):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            return_value=[],
        ):
            result = _detect_regressions()
        assert result["regressions"] == []
        assert result["count"] == 0


class TestFlagged:

    def test_rows_flatten_dataclass(self):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            return_value=[_stub_regression()],
        ):
            result = _detect_regressions()
        assert result["count"] == 1
        row = result["regressions"][0]
        assert row["engine"] == "loyalty"
        assert row["latest_score"] == 4
        assert row["baseline_score"] == 9.0
        assert row["drop"] == 5.0
        assert row["latest_verdict"] == "unhealthy"
        assert row["samples_in_baseline"] == 5

    def test_multiple_regressions(self):
        regs = [
            _stub_regression(engine="loyalty", drop=5.0),
            _stub_regression(
                engine="cart_recovery", drop=3.5,
            ),
        ]
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            return_value=regs,
        ):
            result = _detect_regressions()
        assert result["count"] == 2
        engines = [r["engine"] for r in result["regressions"]]
        assert engines == ["loyalty", "cart_recovery"]


class TestWarningLog:

    def test_warning_fires_when_flagged(self):
        handler, logger_obj = _capture_warnings()
        try:
            with patch(
                "core.approval.engine_health_history."
                "find_regressions",
                return_value=[_stub_regression()],
            ):
                _detect_regressions()
        finally:
            logger_obj.removeHandler(handler)
        warnings = [
            r for r in handler.records
            if r.levelname == "WARNING"
            and "health_regressions" in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "loyalty" in warnings[0].getMessage()
        assert "1 engine" in warnings[0].getMessage()

    def test_no_warning_when_clean(self):
        handler, logger_obj = _capture_warnings()
        try:
            with patch(
                "core.approval.engine_health_history."
                "find_regressions",
                return_value=[],
            ):
                _detect_regressions()
        finally:
            logger_obj.removeHandler(handler)
        warnings = [
            r for r in handler.records
            if r.levelname == "WARNING"
            and "health_regressions" in r.getMessage()
        ]
        assert warnings == []


class TestErrorPaths:

    def test_find_raises_returns_error(self):
        with patch(
            "core.approval.engine_health_history."
            "find_regressions",
            side_effect=RuntimeError("history disk gone"),
        ):
            result = _detect_regressions()
        assert "error" in result
        assert result["count"] == 0
        assert result["regressions"] == []

    def test_import_failure_returns_error(self):
        """Top-level import failure exercises the same fail-open
        path (different except clause)."""
        import builtins
        real_import = builtins.__import__

        def _raise(name, *a, **kw):
            if name == "core.approval.engine_health_history":
                raise ImportError("module gone")
            return real_import(name, *a, **kw)

        with patch("builtins.__import__", side_effect=_raise):
            result = _detect_regressions()
        assert "error" in result
        assert result["count"] == 0
