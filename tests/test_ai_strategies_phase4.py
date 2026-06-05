"""Tests for AI strategies W963-65 agi_phase4 context."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch

from engines._ai_strategies import _agi_phase4_context


@dataclass
class _FakeSummary:
    verdict: str = "earning"
    fleet_gross_profit: float = 412.55
    fleet_attribution_pct: float = 65.5
    monthly_run_rate: float = 1700.0
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


# ── _agi_phase4_context ───────────────────────────────────


class TestAgiPhase4Context:
    def test_default_safe_structure(self):
        ctx = _agi_phase4_context()
        for key in (
            "verdict", "gross_profit", "attribution_pct",
            "trend_verdict", "history_trend_14d",
            "critical_anomaly_count", "top_anomaly_type",
            # W963-76 fields
            "diff_direction", "diff_gross_profit_delta",
            "streak_top", "streak_severity",
            "streak_count",
        ):
            assert key in ctx

    def test_summary_populates_verdict_block(self):
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            return_value=_FakeSummary(),
        ):
            ctx = _agi_phase4_context()
        assert ctx["verdict"] == "earning"
        assert ctx["gross_profit"] == 412.55
        assert ctx["attribution_pct"] == 65.5
        assert ctx["trend_verdict"] == "flat"

    def test_summary_failure_keeps_default(self):
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            side_effect=RuntimeError("boom"),
        ):
            ctx = _agi_phase4_context()
        # Falls back to unknown / 0.0 sentinels
        assert ctx["verdict"] == "unknown"
        assert ctx["gross_profit"] == 0.0

    def test_history_populates_trend(self):
        with patch(
            "engines.agi_earnings_history.store."
            "compute_trend",
            return_value={"verdict": "improving"},
        ):
            ctx = _agi_phase4_context()
        assert ctx["history_trend_14d"] == "improving"

    def test_anomalies_critical_only_counted(self):
        report = _FakeAnomalyReport(anomalies=[
            _FakeAnomaly(
                type="VERDICT_FLIP", severity="critical",
            ),
            _FakeAnomaly(
                type="ORPHAN_BURST", severity="warn",
            ),
            _FakeAnomaly(
                type="ATTRIBUTION_SPIKE", severity="info",
            ),
        ])
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            return_value=report,
        ):
            ctx = _agi_phase4_context()
        assert ctx["critical_anomaly_count"] == 1
        assert ctx["top_anomaly_type"] == "VERDICT_FLIP"

    def test_no_critical_top_is_none(self):
        report = _FakeAnomalyReport(anomalies=[
            _FakeAnomaly(
                type="ORPHAN_BURST", severity="warn",
            ),
        ])
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            return_value=report,
        ):
            ctx = _agi_phase4_context()
        assert ctx["critical_anomaly_count"] == 0
        assert ctx["top_anomaly_type"] is None

    def test_anomaly_failure_keeps_default(self):
        with patch(
            "engines.agi_anomaly_detector.detector.detect",
            side_effect=RuntimeError("x"),
        ):
            ctx = _agi_phase4_context()
        assert ctx["critical_anomaly_count"] == 0
        assert ctx["top_anomaly_type"] is None

    def test_all_substrate_failing_returns_safe_dict(self):
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "compute_summary",
            side_effect=RuntimeError("a"),
        ), patch(
            "engines.agi_earnings_history.store."
            "compute_trend",
            side_effect=RuntimeError("b"),
        ), patch(
            "engines.agi_anomaly_detector.detector.detect",
            side_effect=RuntimeError("c"),
        ):
            ctx = _agi_phase4_context()
        assert ctx["verdict"] == "unknown"
        assert ctx["history_trend_14d"] == "unknown"
        assert ctx["critical_anomaly_count"] == 0
