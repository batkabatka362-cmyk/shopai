"""Tests for ``_check_scope_health`` -- the controller's
Phase 0.7 scope-drift detector.

Lives at module level (mirror of ``_detect_regressions``) so
the autonomous loop can call it once per cycle and tests can
exercise it without spinning up the full controller.

Coverage:
  1. Healthy report flattens granted/required/missing/extra counts.
  2. Missing scopes populate sample_missing (capped at 5).
  3. Extra scopes populate sample_extra.
  4. WARNING log fires when missing_count > 0 (with truncation
     past 5 entries).
  5. No WARNING when healthy.
  6. compare_to_live returning None ⇒ live_data_unavailable.
  7. compare_to_live raising ⇒ probe_failed envelope.
  8. ImportError ⇒ import_failed envelope.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

from core.autonomous.controller import _check_scope_health


def _stub_report(
    *, granted=None, required=None,
    missing=None, extra=None,
):
    from core.adapters.shopify.scope_health import ScopeHealthReport
    granted = granted or set()
    required = required or set()
    missing = missing or []
    extra = extra or []
    return ScopeHealthReport(
        granted_scopes=frozenset(granted),
        required_scopes=frozenset(required),
        missing_from_app=list(missing),
        extra_in_app=list(extra),
        is_healthy=not missing,
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


# ─── Healthy case ────────────────────────────────────────────


class TestHealthy:

    def test_healthy_flattens_counts(self):
        report = _stub_report(
            granted={"read_orders", "write_orders"},
            required={"read_orders", "write_orders"},
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            result = _check_scope_health()
        assert result["checked"] is True
        assert result["is_healthy"] is True
        assert result["granted_count"] == 2
        assert result["required_count"] == 2
        assert result["missing_count"] == 0
        assert result["extra_count"] == 0
        assert result["sample_missing"] == []
        assert result["sample_extra"] == []


# ─── Drift cases ─────────────────────────────────────────────


class TestDrift:

    def test_missing_scopes_populate_sample(self):
        report = _stub_report(
            granted={"read_orders"},
            required={
                "read_orders", "write_orders", "read_products",
            },
            missing=["read_products", "write_orders"],
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            result = _check_scope_health()
        assert result["is_healthy"] is False
        assert result["missing_count"] == 2
        assert "read_products" in result["sample_missing"]
        assert "write_orders" in result["sample_missing"]

    def test_sample_missing_capped_at_5(self):
        many = [f"scope_{i}" for i in range(20)]
        report = _stub_report(
            granted=set(),
            required=set(many),
            missing=sorted(many),
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            result = _check_scope_health()
        assert result["missing_count"] == 20
        assert len(result["sample_missing"]) == 5

    def test_extra_scopes_populate_sample(self):
        report = _stub_report(
            granted={
                "read_orders", "read_unused_a", "read_unused_b",
            },
            required={"read_orders"},
            extra=["read_unused_a", "read_unused_b"],
        )
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=report,
        ):
            result = _check_scope_health()
        # Extras don't break health
        assert result["is_healthy"] is True
        assert result["extra_count"] == 2
        assert "read_unused_a" in result["sample_extra"]


# ─── Warning log ─────────────────────────────────────────────


class TestWarningLog:

    def test_warning_fires_when_missing(self):
        handler, logger_obj = _capture_warnings()
        try:
            report = _stub_report(
                granted={"read_orders"},
                required={"read_orders", "write_orders"},
                missing=["write_orders"],
            )
            with patch(
                "core.adapters.shopify.scope_health.compare_to_live",
                return_value=report,
            ):
                _check_scope_health()
        finally:
            logger_obj.removeHandler(handler)
        warnings = [
            r for r in handler.records
            if r.levelname == "WARNING"
            and "scope_health" in r.getMessage()
        ]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "write_orders" in msg
        assert "1 scope" in msg
        assert "ACCESS_DENIED" in msg

    def test_warning_truncates_past_5(self):
        handler, logger_obj = _capture_warnings()
        try:
            missing = [f"scope_{i}" for i in range(10)]
            report = _stub_report(
                granted=set(),
                required=set(missing),
                missing=missing,
            )
            with patch(
                "core.adapters.shopify.scope_health.compare_to_live",
                return_value=report,
            ):
                _check_scope_health()
        finally:
            logger_obj.removeHandler(handler)
        warnings = [
            r for r in handler.records
            if r.levelname == "WARNING"
            and "scope_health" in r.getMessage()
        ]
        assert len(warnings) == 1
        msg = warnings[0].getMessage()
        assert "+5 more" in msg

    def test_no_warning_when_healthy(self):
        handler, logger_obj = _capture_warnings()
        try:
            report = _stub_report(
                granted={"read_orders"},
                required={"read_orders"},
            )
            with patch(
                "core.adapters.shopify.scope_health.compare_to_live",
                return_value=report,
            ):
                _check_scope_health()
        finally:
            logger_obj.removeHandler(handler)
        warnings = [
            r for r in handler.records
            if r.levelname == "WARNING"
            and "scope_health" in r.getMessage()
        ]
        assert warnings == []

    def test_no_warning_when_only_extras(self):
        """Extras don't break health -- no WARNING."""
        handler, logger_obj = _capture_warnings()
        try:
            report = _stub_report(
                granted={"read_orders", "read_unused"},
                required={"read_orders"},
                extra=["read_unused"],
            )
            with patch(
                "core.adapters.shopify.scope_health.compare_to_live",
                return_value=report,
            ):
                _check_scope_health()
        finally:
            logger_obj.removeHandler(handler)
        warnings = [
            r for r in handler.records
            if r.levelname == "WARNING"
            and "scope_health" in r.getMessage()
        ]
        assert warnings == []


# ─── Error paths ─────────────────────────────────────────────


class TestErrorPaths:

    def test_compare_returns_none_yields_unavailable(self):
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            return_value=None,
        ):
            result = _check_scope_health()
        assert result["checked"] is False
        assert result["error"] == "live_data_unavailable"

    def test_compare_raises_yields_probe_failed(self):
        """compare_to_live should swallow its own errors and
        return None; belt-and-braces if a future change skips
        that guard."""
        with patch(
            "core.adapters.shopify.scope_health.compare_to_live",
            side_effect=RuntimeError("network died"),
        ):
            result = _check_scope_health()
        assert result["checked"] is False
        assert "probe_failed" in result["error"]
        assert "network died" in result["error"]

    def test_import_failure_returns_envelope(self):
        """Top-level import failure exercises a different
        except clause -- same fail-open contract."""
        import builtins
        real_import = builtins.__import__

        def _raise(name, *a, **kw):
            if name == "core.adapters.shopify.scope_health":
                raise ImportError("module gone")
            return real_import(name, *a, **kw)

        with patch("builtins.__import__", side_effect=_raise):
            result = _check_scope_health()
        assert result["checked"] is False
        assert "import_failed" in result["error"]
