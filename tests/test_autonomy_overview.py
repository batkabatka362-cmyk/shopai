"""Tests for core.automation.autonomy_overview (W892)."""
from __future__ import annotations

from unittest.mock import patch

from core.automation.autonomy_overview import (
    OverviewSnapshot,
    build_overview,
)


class TestSnapshot:

    def test_defaults(self):
        s = OverviewSnapshot()
        assert s.armed_total == 0
        assert s.fires_total == 0
        assert s.captured_at > 0

    def test_verdict_idle_when_nothing_armed(self):
        s = OverviewSnapshot()
        assert s.verdict == "idle"

    def test_verdict_armed_when_armed_no_activity(self):
        s = OverviewSnapshot(armed_total=2)
        assert s.verdict == "armed"

    def test_verdict_active_when_fires_invoked(self):
        s = OverviewSnapshot(
            armed_total=1, fires_invoked=3,
        )
        assert s.verdict == "active"

    def test_verdict_degraded_on_critical_alerts(self):
        s = OverviewSnapshot(alerts_critical=1)
        assert s.verdict == "degraded"

    def test_verdict_degraded_on_errors(self):
        s = OverviewSnapshot(fires_errors=2)
        assert s.verdict == "degraded"


class TestBuildOverview:

    def test_runs_clean_without_data(self):
        # Pattern J guards prevent live persistence under
        # pytest; build_overview reads the (empty) state.
        snap = build_overview()
        assert isinstance(snap, OverviewSnapshot)
        assert snap.verdict in (
            "idle", "armed", "active", "degraded",
        )
        # Counts may be 0 (typical idle dev state)

    def test_window_hours_propagated(self):
        snap = build_overview(window_hours=72.0)
        assert snap.window_hours == 72.0

    def test_store_id_propagated(self):
        snap = build_overview(store_id="store-7")
        assert snap.store_id == "store-7"

    def test_alert_count_drives_degraded(self):
        from core.automation.substrate_fire_alerts import (
            FireAlertsReport,
        )
        report = FireAlertsReport()
        # Synthesise critical alert
        from core.automation.substrate_fire_alerts import (
            FireAlert,
        )
        report.alerts.append(FireAlert(
            domain="x", kind="low_success_rate",
            severity="critical", reason="test",
        ))
        with patch(
            "core.automation.substrate_fire_alerts."
            "compute_fire_alerts",
            return_value=report,
        ):
            snap = build_overview()
        assert snap.alerts_critical == 1
        assert snap.verdict == "degraded"
