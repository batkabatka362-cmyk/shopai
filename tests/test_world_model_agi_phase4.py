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
            # W963-76 fields
            "diff_direction", "diff_gross_profit_delta",
            "diff_verdict_change",
            "streak_top", "streak_severity",
            "streak_count",
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

    def test_diff_population(self):
        """W963-76: brief-diff direction should be exposed."""
        wm = WorldModel()

        @dataclass
        class _FakeDiff:
            sufficient: bool = True
            direction: str = "regressed"
            verdict_change: str = "regressed"
            gross_profit_delta: float = -100.0

        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=_FakeDiff(),
        ):
            section = wm._section_agi_phase4()
        assert section["diff_direction"] == "regressed"
        assert section["diff_gross_profit_delta"] == -100.0
        assert section["diff_verdict_change"] == "regressed"

    def test_diff_insufficient_keeps_default(self):
        wm = WorldModel()

        @dataclass
        class _FakeDiff:
            sufficient: bool = False
            direction: str = "no_data"
            verdict_change: str = "no_change"
            gross_profit_delta: float = 0.0

        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            return_value=_FakeDiff(),
        ):
            section = wm._section_agi_phase4()
        # When sufficient=False, fields stay at default
        assert section["diff_direction"] is None
        assert section["diff_verdict_change"] is None

    def test_streak_population(self):
        wm = WorldModel()

        @dataclass
        class _FakeStreak:
            name: str = "loss_streak"
            count: int = 5
            severity: str = "warn"

        @dataclass
        class _FakeStreakReport:
            attention_needed: bool = True
            top_streak: str = "loss_streak"
            loss_streak: _FakeStreak = field(
                default_factory=_FakeStreak,
            )
            no_data_streak: _FakeStreak = field(
                default_factory=_FakeStreak,
            )
            anomaly_streak: _FakeStreak = field(
                default_factory=_FakeStreak,
            )

        with patch(
            "engines.agi_recommend_streak.detector."
            "detect_streaks",
            return_value=_FakeStreakReport(),
        ):
            section = wm._section_agi_phase4()
        assert section["streak_top"] == "loss_streak"
        assert section["streak_severity"] == "warn"
        assert section["streak_count"] == 5

    def test_streak_failure_fails_open(self):
        wm = WorldModel()
        with patch(
            "engines.agi_recommend_streak.detector."
            "detect_streaks",
            side_effect=RuntimeError("x"),
        ):
            section = wm._section_agi_phase4()
        assert section["checked"] is True
        assert section["streak_top"] is None
        assert section["streak_severity"] == "info"

    def test_diff_failure_fails_open(self):
        wm = WorldModel()
        with patch(
            "engines.agi_brief_diff.differ.compute_diff",
            side_effect=RuntimeError("x"),
        ):
            section = wm._section_agi_phase4()
        assert section["checked"] is True
        assert section["diff_direction"] is None

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
