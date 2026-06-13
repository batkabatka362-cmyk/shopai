"""Tests for engines._health_endpoint."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from engines._health_endpoint import health_report


class TestHealthShape:
    """The report has the expected top-level keys + nested
    component dicts."""

    def test_returns_required_keys(self):
        report = health_report()
        assert "captured_at" in report
        assert "healthy" in report
        assert "components" in report
        assert "failures" in report

    def test_components_dict_has_four_sub_checks(self):
        report = health_report()
        components = report["components"]
        assert "cycle" in components
        assert "alerts" in components
        assert "quarantine" in components
        assert "stores" in components

    def test_each_component_has_status(self):
        report = health_report()
        for name, c in report["components"].items():
            assert "status" in c, (
                f"component {name} missing status"
            )

    def test_healthy_is_bool(self):
        report = health_report()
        assert isinstance(report["healthy"], bool)


class TestCycleAgeCheck:

    def test_no_cycle_history_marks_warn(self):
        with patch(
            "engines._cycle_history.last_run",
            return_value=None,
        ):
            report = health_report()
        cycle = report["components"]["cycle"]
        assert cycle["status"] == "warn"
        assert cycle.get("age_hours") is None

    def test_old_cycle_marks_fail_and_unhealthy(self):
        # 100 hours ago
        old_run = SimpleNamespace(
            started_at=__import__("time").time() - 100 * 3600,
        )
        with patch(
            "engines._cycle_history.last_run",
            return_value=old_run,
        ):
            report = health_report()
        cycle = report["components"]["cycle"]
        assert cycle["status"] == "fail"
        assert "stale_cycle" in report["failures"]
        assert report["healthy"] is False

    def test_recent_cycle_marks_ok(self):
        recent = SimpleNamespace(
            started_at=__import__("time").time() - 1 * 3600,
        )
        with patch(
            "engines._cycle_history.last_run",
            return_value=recent,
        ):
            report = health_report()
        cycle = report["components"]["cycle"]
        assert cycle["status"] == "ok"


class TestAlertsCheck:

    def test_no_alerts_marks_ok(self):
        with patch(
            "engines._notify.collect_alerts",
            return_value=[],
        ):
            report = health_report()
        alerts = report["components"]["alerts"]
        assert alerts["status"] == "ok"
        assert alerts["count"] == 0

    def test_warn_alerts_dont_unhealthy(self):
        from engines._notify import NotifyAlert
        with patch(
            "engines._notify.collect_alerts",
            return_value=[
                NotifyAlert(
                    kind="x", severity="warn", message="y",
                ),
            ],
        ), patch(
            "engines._cycle_history.last_run",
            return_value=None,  # avoid stale_cycle fail
        ):
            report = health_report()
        alerts = report["components"]["alerts"]
        assert alerts["status"] == "warn"
        # warn alerts alone don't make UNHEALTHY
        # (only critical do)
        # but if other components fail, healthy could be False
        # -- the test asserts the alerts-level decision:
        assert "critical_alert_x" not in report["failures"]

    def test_critical_alert_makes_unhealthy(self):
        from engines._notify import NotifyAlert
        with patch(
            "engines._notify.collect_alerts",
            return_value=[
                NotifyAlert(
                    kind="spend_breach", severity="critical",
                    message="cap blown",
                ),
            ],
        ):
            report = health_report()
        assert report["healthy"] is False
        assert any(
            f.startswith("critical_alert")
            for f in report["failures"]
        )
