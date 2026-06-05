"""Tests for notify AGI anomaly integration (W963-63)."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch


@dataclass
class _FakeAnomaly:
    type: str
    severity: str
    delta: float
    description: str
    occurred_at: float = 0.0


@dataclass
class _FakeReport:
    anomalies: list


class TestAgiAnomalyProbe:
    def test_critical_anomaly_emits_alert(self):
        from engines._notify import collect_alerts
        fake = _FakeReport(anomalies=[
            _FakeAnomaly(
                type="VERDICT_FLIP", severity="critical",
                delta=0,
                description="Latest verdict=...",
                occurred_at=1234.0,
            ),
        ])
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            return_value=fake,
        ):
            alerts = collect_alerts()
        agi_alerts = [
            a for a in alerts
            if a.kind == "agi_critical_anomaly"
        ]
        assert len(agi_alerts) == 1
        assert agi_alerts[0].severity == "critical"
        assert "VERDICT_FLIP" in agi_alerts[0].message

    def test_warn_anomaly_does_not_emit(self):
        from engines._notify import collect_alerts
        fake = _FakeReport(anomalies=[
            _FakeAnomaly(
                type="ORPHAN_BURST", severity="warn",
                delta=10,
                description="x",
            ),
        ])
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            return_value=fake,
        ):
            alerts = collect_alerts()
        agi_alerts = [
            a for a in alerts
            if a.kind == "agi_critical_anomaly"
        ]
        assert agi_alerts == []

    def test_info_anomaly_does_not_emit(self):
        from engines._notify import collect_alerts
        fake = _FakeReport(anomalies=[
            _FakeAnomaly(
                type="ATTRIBUTION_SPIKE", severity="info",
                delta=60,
                description="x",
            ),
        ])
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            return_value=fake,
        ):
            alerts = collect_alerts()
        agi_alerts = [
            a for a in alerts
            if a.kind == "agi_critical_anomaly"
        ]
        assert agi_alerts == []

    def test_only_one_anomaly_pushed_when_multiple(self):
        """Multiple critical -> only one notify alert."""
        from engines._notify import collect_alerts
        fake = _FakeReport(anomalies=[
            _FakeAnomaly(
                type="VERDICT_FLIP", severity="critical",
                delta=0, description="x",
            ),
            _FakeAnomaly(
                type="PROFIT_OUTLIER", severity="critical",
                delta=-500, description="y",
            ),
        ])
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            return_value=fake,
        ):
            alerts = collect_alerts()
        agi_alerts = [
            a for a in alerts
            if a.kind == "agi_critical_anomaly"
        ]
        assert len(agi_alerts) == 1
        # First (critical, sorted by W963-57) wins
        assert "VERDICT_FLIP" in agi_alerts[0].message

    def test_detector_raises_swallowed(self):
        """Exception in detector must not break notify."""
        from engines._notify import collect_alerts
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            side_effect=RuntimeError("boom"),
        ):
            alerts = collect_alerts()
        # Just confirm we got a list back -- other probes
        # still fire
        assert isinstance(alerts, list)

    def test_no_anomalies_no_alert(self):
        from engines._notify import collect_alerts
        fake = _FakeReport(anomalies=[])
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            return_value=fake,
        ):
            alerts = collect_alerts()
        agi_alerts = [
            a for a in alerts
            if a.kind == "agi_critical_anomaly"
        ]
        assert agi_alerts == []

    def test_alert_carries_context(self):
        from engines._notify import collect_alerts
        fake = _FakeReport(anomalies=[
            _FakeAnomaly(
                type="ATTRIBUTION_COLLAPSE",
                severity="critical",
                delta=-65.5,
                description="x",
                occurred_at=1234567.0,
            ),
        ])
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            return_value=fake,
        ):
            alerts = collect_alerts()
        agi_alerts = [
            a for a in alerts
            if a.kind == "agi_critical_anomaly"
        ]
        ctx = agi_alerts[0].context
        assert ctx["type"] == "ATTRIBUTION_COLLAPSE"
        assert ctx["delta"] == -65.5
        assert ctx["occurred_at"] == 1234567.0
