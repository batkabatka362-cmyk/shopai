"""Tests for engines.agi_earnings_summary — W963-48."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch

from engines.agi_earnings_summary import (
    AgiEarningsSummaryEngine,
)
from engines.agi_earnings_summary.summarizer import (
    EarningsSummary,
    _classify_verdict,
    compute_summary,
)


# ── _classify_verdict ─────────────────────────────────────


class TestClassifyVerdict:
    def test_no_data(self):
        assert _classify_verdict(0.0, 0.0, 0.0) == "no_data"

    def test_organic_only(self):
        assert (
            _classify_verdict(0.0, 100.0, 50.0)
            == "organic_only"
        )

    def test_attributed_loss(self):
        assert (
            _classify_verdict(100.0, 50.0, -10.0)
            == "attributed_loss"
        )

    def test_earning(self):
        assert (
            _classify_verdict(100.0, 50.0, 25.0) == "earning"
        )


# ── compute_summary with fakes ────────────────────────────


@dataclass
class _FakePnl:
    store_id: str = "s1"
    gross_revenue: float = 100.0
    gross_profit: float = 25.0
    verdict: str = "profitable"


@dataclass
class _FakeFleetPnl:
    fleet_gross_profit: float = 25.0
    fleet_margin_pct: float = 25.0
    by_store: list = field(default_factory=list)


@dataclass
class _FakeRecon:
    fleet_attributed_revenue: float = 100.0
    fleet_organic_revenue: float = 50.0
    fleet_attribution_pct: float = 66.7
    fleet_orphan_action_count: int = 0


class TestComputeSummary:
    def test_no_data_when_all_empty(self):
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "_compute_reconciliation",
            return_value=None,
        ), patch(
            "engines.agi_earnings_summary.summarizer."
            "_compute_pnl",
            return_value=None,
        ), patch(
            "engines.agi_earnings_summary.summarizer."
            "_fleet_trend",
            return_value="no_data",
        ):
            s = compute_summary(days=7)
        assert s.verdict == "no_data"

    def test_earning_verdict(self):
        fake_pnl = _FakeFleetPnl(
            fleet_gross_profit=25.0,
            fleet_margin_pct=25.0,
            by_store=[_FakePnl()],
        )
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "_compute_reconciliation",
            return_value=_FakeRecon(),
        ), patch(
            "engines.agi_earnings_summary.summarizer."
            "_compute_pnl",
            return_value=fake_pnl,
        ), patch(
            "engines.agi_earnings_summary.summarizer."
            "_fleet_trend",
            return_value="rising",
        ):
            s = compute_summary(days=7)
        assert s.verdict == "earning"
        assert s.fleet_attributed_revenue == 100.0
        assert s.fleet_gross_profit == 25.0
        assert s.profitable_store_count == 1
        assert s.trend_verdict == "rising"
        # Monthly run rate: 25 / 7 * 30 ≈ 107.14
        assert abs(s.monthly_run_rate - 107.14) < 0.5

    def test_attributed_loss(self):
        fake_pnl = _FakeFleetPnl(
            fleet_gross_profit=-10.0,
            fleet_margin_pct=-5.0,
            by_store=[
                _FakePnl(
                    store_id="s1", gross_profit=-10.0,
                    verdict="loss",
                ),
            ],
        )
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "_compute_reconciliation",
            return_value=_FakeRecon(),
        ), patch(
            "engines.agi_earnings_summary.summarizer."
            "_compute_pnl",
            return_value=fake_pnl,
        ), patch(
            "engines.agi_earnings_summary.summarizer."
            "_fleet_trend",
            return_value="falling",
        ):
            s = compute_summary(days=7)
        assert s.verdict == "attributed_loss"
        assert s.loss_store_count == 1
        assert s.profitable_store_count == 0

    def test_organic_only(self):
        recon = _FakeRecon(
            fleet_attributed_revenue=0.0,
            fleet_organic_revenue=200.0,
            fleet_attribution_pct=0.0,
        )
        fake_pnl = _FakeFleetPnl(
            fleet_gross_profit=50.0, by_store=[_FakePnl()],
        )
        with patch(
            "engines.agi_earnings_summary.summarizer."
            "_compute_reconciliation",
            return_value=recon,
        ), patch(
            "engines.agi_earnings_summary.summarizer."
            "_compute_pnl",
            return_value=fake_pnl,
        ), patch(
            "engines.agi_earnings_summary.summarizer."
            "_fleet_trend",
            return_value="flat",
        ):
            s = compute_summary(days=7)
        assert s.verdict == "organic_only"


# ── Envelope (Pattern Q) ──────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AgiEarningsSummaryEngine().run({})
        assert r["status"] == "success"
        assert "data" in r
        assert "meta" in r
        assert "error" in r

    def test_none_success(self):
        r = AgiEarningsSummaryEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AgiEarningsSummaryEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AgiEarningsSummaryEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AgiEarningsSummaryEngine().run({})
        assert (
            r["meta"]["engine"] == "agi_earnings_summary"
        )

    def test_invalid_days_falls_back(self):
        r = AgiEarningsSummaryEngine().run({
            "data": {"days": "abc"},
        })
        assert r["data"]["days"] == 7

    def test_invalid_window_falls_back(self):
        r = AgiEarningsSummaryEngine().run({
            "data": {"attribution_window_hours": "xyz"},
        })
        assert (
            r["data"]["attribution_window_hours"] == 48.0
        )

    def test_invalid_trend_days_falls_back(self):
        r = AgiEarningsSummaryEngine().run({
            "data": {"trend_days": "xyz"},
        })
        # Output dataclass doesn't carry trend_days; just
        # confirm engine didn't crash
        assert r["status"] == "success"

    def test_next_action_present(self):
        r = AgiEarningsSummaryEngine().run({})
        assert "next_action" in r["data"]
        assert r["data"]["next_action"]
