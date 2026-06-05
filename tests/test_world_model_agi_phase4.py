"""Tests for world-model agi_phase4 section (W963-64)."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch

from core.world_model.snapshot import WorldModel


@dataclass
class _FakeSummary:
    verdict: str = "earning"
    fleet_gross_profit: float = 250.0
    fleet_attribution_pct: float = 72.5
    monthly_run_rate: float = 1000.0
    trend_verdict: str = "flat"


@dataclass
class _FakeAnomaly:
    type: str
    severity: str
    delta: float = 0.0
    description: str = "x"
    occurred_at: float = 0.0


@dataclass
class _FakeAnomalyReport:
    anomalies: list = field(default_factory=list)


# ── _section_agi_phase4 ───────────────────────────────────


class TestSectionAgiPhase4:
    def test_default_structure(self):
        wm = WorldModel()
        # No mocks -> real substrate. Should at least return
        # checked=True with the expected keys.
        section = wm._section_agi_phase4()
        for key in (
            "checked", "scope", "verdict",
            "gross_profit", "attribution_pct",
            "monthly_run_rate", "trend_verdict",
            "history_snapshots", "history_trend",
            "anomalies_critical", "anomalies_total",
            "anomalies_top",
        ):
            assert key in section
        assert section["checked"] is True
        assert section["scope"] == "fleet"

    def test_populates_summary_fields(self):
        wm = WorldModel()
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            return_value=_FakeSummary(),
        ):
            section = wm._section_agi_phase4()
        assert section["verdict"] == "earning"
        assert section["gross_profit"] == 250.0
        assert section["attribution_pct"] == 72.5
        assert section["monthly_run_rate"] == 1000.0
        assert section["trend_verdict"] == "flat"

    def test_summary_failure_fails_open(self):
        wm = WorldModel()
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            side_effect=RuntimeError("boom"),
        ):
            section = wm._section_agi_phase4()
        assert section["checked"] is True
        # Verdict stays None on summary failure
        assert section["verdict"] is None

    def test_history_population(self):
        wm = WorldModel()
        with patch(
            "engines.agi_earnings_history.store."
            "snapshot_count",
            return_value=20,
        ), patch(
            "engines.agi_earnings_history.store."
            "compute_trend",
            return_value={"verdict": "improving"},
        ):
            section = wm._section_agi_phase4()
        assert section["history_snapshots"] == 20
        assert section["history_trend"] == "improving"

    def test_anomalies_population(self):
        wm = WorldModel()
        report = _FakeAnomalyReport(anomalies=[
            _FakeAnomaly(
                type="VERDICT_FLIP",
                severity="critical",
                description="d1",
            ),
            _FakeAnomaly(
                type="ORPHAN_BURST",
                severity="warn",
                description="d2",
            ),
        ])
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            return_value=report,
        ):
            section = wm._section_agi_phase4()
        assert section["anomalies_total"] == 2
        assert section["anomalies_critical"] == 1
        # Top is the first (assumed critical-first sorted
        # by the detector)
        assert section["anomalies_top"]["type"] == (
            "VERDICT_FLIP"
        )

    def test_anomaly_failure_fails_open(self):
        wm = WorldModel()
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            side_effect=RuntimeError("x"),
        ):
            section = wm._section_agi_phase4()
        assert section["checked"] is True
        assert section["anomalies_total"] == 0
        assert section["anomalies_critical"] == 0
        assert section["anomalies_top"] is None


# ── snapshot() integration ────────────────────────────────


class TestSnapshotIntegration:
    def test_snapshot_carries_agi_phase4_key(self):
        wm = WorldModel()
        snap = wm.snapshot(
            store_id="nonexistent_test_store",
            skip_live=True,
        )
        assert "agi_phase4" in snap

    def test_snapshot_agi_phase4_is_dict_with_keys(self):
        wm = WorldModel()
        snap = wm.snapshot(
            store_id="nonexistent_test_store",
            skip_live=True,
        )
        section = snap["agi_phase4"]
        assert isinstance(section, dict)
        assert section.get("checked") is True
        assert section.get("scope") == "fleet"
