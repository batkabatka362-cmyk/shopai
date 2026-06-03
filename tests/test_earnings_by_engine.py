"""Tests for engines.earnings_by_engine — W963-19."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines.earnings_by_engine import EarningsByEngineEngine
from engines.earnings_by_engine.analyzer import (
    EngineEarnings,
    analyze_earnings_by_engine,
    w963_roster,
)


# ── Roster ────────────────────────────────────────────────


class TestRoster:
    def test_roster_size_is_18(self):
        # 16 W963 engines (1-16) + warmup_plan + today_brief +
        # earnings_by_engine (meta-engines, intro_day=0).
        assert len(w963_roster()) == 18

    def test_all_introduced_within_30_days(self):
        for name, day in w963_roster().items():
            assert 0 <= day <= 30, name

    def test_returns_independent_dict(self):
        r = w963_roster()
        r["fake_engine"] = 99
        assert "fake_engine" not in w963_roster()


# ── Analyzer ───────────────────────────────────────────────


class TestAnalyzer:
    def test_no_attribution_returns_roster_no_data(self):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            side_effect=Exception("nope"),
        ):
            r = analyze_earnings_by_engine()
        assert len(r.engines) == 18
        assert all(e.verdict == "no_data" for e in r.engines)
        assert r.no_data_count == 18

    def test_empty_attribution_returns_roster_no_data(self):
        fake_attr = MagicMock()
        fake_attr.per_engine = []
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=fake_attr,
        ):
            r = analyze_earnings_by_engine()
        assert all(e.verdict == "no_data" for e in r.engines)

    def test_earning_engine_classified(self):
        fake_ea = MagicMock()
        fake_ea.engine = "review_request"
        fake_ea.attributed_orders = 5
        fake_ea.attributed_revenue = 250.0
        fake_ea.confidence = "high"
        fake_attr = MagicMock()
        fake_attr.per_engine = [fake_ea]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=fake_attr,
        ):
            r = analyze_earnings_by_engine()
        rr = [
            e for e in r.engines
            if e.engine == "review_request"
        ][0]
        assert rr.attributed_revenue == 250.0
        assert rr.verdict == "earning"
        assert r.earning_count == 1

    def test_flat_below_threshold(self):
        fake_ea = MagicMock()
        fake_ea.engine = "tiktok_publisher"
        fake_ea.attributed_orders = 1
        fake_ea.attributed_revenue = 5.0
        fake_ea.confidence = "low"
        fake_attr = MagicMock()
        fake_attr.per_engine = [fake_ea]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=fake_attr,
        ):
            r = analyze_earnings_by_engine()
        tk = [
            e for e in r.engines
            if e.engine == "tiktok_publisher"
        ][0]
        assert tk.verdict == "flat"
        # earning_count should NOT include flat verdict.
        assert r.earning_count == 0

    def test_window_hours_propagated(self):
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            side_effect=Exception("nope"),
        ):
            r = analyze_earnings_by_engine(window_hours=720.0)
        assert r.window_hours == 720.0

    def test_unknown_engine_excluded(self):
        fake_ea = MagicMock()
        fake_ea.engine = "some_other_engine_not_in_w963"
        fake_ea.attributed_orders = 10
        fake_ea.attributed_revenue = 1000.0
        fake_attr = MagicMock()
        fake_attr.per_engine = [fake_ea]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=fake_attr,
        ):
            r = analyze_earnings_by_engine()
        # The roster has 18 engines; the unknown one isn't
        # included.
        assert len(r.engines) == 18
        assert all(
            e.engine != "some_other_engine_not_in_w963"
            for e in r.engines
        )


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_input_success(self):
        result = EarningsByEngineEngine().run({})
        assert result["status"] == "success"
        assert result["data"]["window_hours"] == 168.0

    def test_none_input_success(self):
        result = EarningsByEngineEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_error(self):
        result = EarningsByEngineEngine().run("nope")
        assert result["status"] == "error"

    def test_fail_upstream(self):
        result = EarningsByEngineEngine().run({
            "status": "fail", "error": "broken",
        })
        assert result["status"] == "error"

    def test_carries_engine_name(self):
        result = EarningsByEngineEngine().run({})
        assert result["meta"]["engine"] == "earnings_by_engine"


class TestEngineActions:
    def test_invalid_window_hours_falls_back_to_default(self):
        result = EarningsByEngineEngine().run({
            "data": {"window_hours": "not-a-number"},
        })
        assert result["data"]["window_hours"] == 168.0

    def test_custom_window_threaded(self):
        result = EarningsByEngineEngine().run({
            "data": {"window_hours": 24.0},
        })
        assert result["data"]["window_hours"] == 24.0

    def test_store_id_threaded(self):
        result = EarningsByEngineEngine().run({
            "data": {"store_id": "main"},
        })
        assert result["data"]["store_id"] == "main"

    def test_emits_18_engines(self):
        result = EarningsByEngineEngine().run({})
        assert len(result["data"]["engines"]) == 18

    def test_engines_sorted_by_intro_day(self):
        result = EarningsByEngineEngine().run({})
        days = [
            e["intro_day"] for e in result["data"]["engines"]
        ]
        assert days == sorted(days)


# ── Next action ────────────────────────────────────────────


class TestNextAction:
    def test_no_orders_says_wait(self):
        result = EarningsByEngineEngine().run({})
        nxt = result["data"]["next_action"]
        assert "Wait" in nxt or "extend window" in nxt
