"""Tests for engines.earnings_report — W963-4."""
from __future__ import annotations

import time
from unittest.mock import patch

from engines.earnings_report import EarningsReportEngine
from engines.earnings_report.analyzer import (
    EarningsReport,
    WindowSummary,
    _parse_iso,
    _safe_amount,
    _verdict,
    analyze,
    to_dict,
)


_NOW = 1_900_000_000.0  # Deterministic fake "now" for windowing.


def _iso_at(offset_hours: float, base: float = _NOW) -> str:
    """Build an ISO timestamp at base + offset_hours (so negative
    = past)."""
    return time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(base + offset_hours * 3600.0),
    )


def _order(
    *,
    hours_ago: float,
    total: float = 50.0,
    refunded: float = 0.0,
    cancelled: bool = False,
    currency: str = "USD",
) -> dict:
    return {
        "created_at": _iso_at(-hours_ago),
        "total_price": total,
        "refunded_price": refunded,
        "cancelled_at": _iso_at(-hours_ago + 1) if cancelled else "",
        "currency_code": currency,
    }


# ── Helpers ─────────────────────────────────────────────────


class TestParseIso:
    def test_parses_z_suffix(self):
        ts = _parse_iso("2026-06-03T00:00:00Z")
        assert ts is not None
        assert ts > 0

    def test_returns_none_for_garbage(self):
        assert _parse_iso("not a date") is None
        assert _parse_iso("") is None
        assert _parse_iso(None) is None
        assert _parse_iso(123) is None


class TestSafeAmount:
    def test_handles_int_float_str(self):
        assert _safe_amount(10) == 10.0
        assert _safe_amount(10.5) == 10.5
        assert _safe_amount("10.99") == 10.99

    def test_unparseable_returns_zero(self):
        assert _safe_amount("free") == 0.0
        assert _safe_amount(None) == 0.0
        assert _safe_amount({}) == 0.0


# ── Verdict bands ───────────────────────────────────────────


class TestVerdict:
    def test_both_zero_is_cold(self):
        assert _verdict(0.0, 0.0) == "cold"

    def test_previous_zero_current_positive_is_earning(self):
        assert _verdict(50.0, 0.0) == "earning"

    def test_strong_growth_is_earning(self):
        assert _verdict(200.0, 100.0) == "earning"

    def test_small_change_is_flat(self):
        assert _verdict(105.0, 100.0) == "flat"

    def test_steep_drop_is_declining(self):
        assert _verdict(50.0, 100.0) == "declining"


# ── Analyzer windowing ──────────────────────────────────────


class TestAnalyzer:
    def test_empty_orders_returns_zero_report(self):
        r = analyze(
            orders=[], window_hours=24.0, now=_NOW,
        )
        assert r.current.revenue == 0.0
        assert r.previous.revenue == 0.0
        assert r.verdict == "cold"

    def test_today_excludes_yesterday(self):
        # Window=24h: current = -24h..0; previous = -48h..-24h
        orders = [
            _order(hours_ago=2, total=100.0),    # current
            _order(hours_ago=30, total=50.0),    # previous
            _order(hours_ago=72, total=999.0),   # excluded
        ]
        r = analyze(
            orders=orders, window_hours=24.0, now=_NOW,
        )
        assert r.current.revenue == 100.0
        assert r.previous.revenue == 50.0
        assert r.current.order_count == 1
        assert r.previous.order_count == 1
        assert r.delta == 50.0
        assert r.delta_pct == 100.0
        assert r.verdict == "earning"

    def test_refunded_subtracted_from_revenue(self):
        orders = [
            _order(hours_ago=2, total=100.0, refunded=30.0),
        ]
        r = analyze(
            orders=orders, window_hours=24.0, now=_NOW,
        )
        assert r.current.revenue == 70.0

    def test_cancelled_order_excluded(self):
        orders = [
            _order(hours_ago=2, total=100.0, cancelled=True),
            _order(hours_ago=3, total=50.0),
        ]
        r = analyze(
            orders=orders, window_hours=24.0, now=_NOW,
        )
        assert r.current.revenue == 50.0
        assert r.current.order_count == 1

    def test_aov_computed(self):
        orders = [
            _order(hours_ago=1, total=100.0),
            _order(hours_ago=2, total=50.0),
        ]
        r = analyze(
            orders=orders, window_hours=24.0, now=_NOW,
        )
        assert r.current.order_count == 2
        assert r.current.revenue == 150.0
        assert r.current.avg_order_value == 75.0

    def test_currency_first_non_empty_wins(self):
        orders = [
            _order(hours_ago=1, currency="USD"),
            _order(hours_ago=2, currency="EUR"),
        ]
        r = analyze(
            orders=orders, window_hours=24.0, now=_NOW,
        )
        assert r.current.currency == "USD"

    def test_non_dict_orders_skipped(self):
        orders = ["bad", None, _order(hours_ago=1, total=50.0)]
        r = analyze(
            orders=orders, window_hours=24.0, now=_NOW,
        )
        assert r.current.order_count == 1


# ── Pattern Q envelope ─────────────────────────────────────


class TestEngineEnvelope:
    def test_empty_input_returns_success(self):
        # The hydrator call inside run() reads from a live store
        # — patch it to return [] so the test is self-contained.
        with patch(
            "engines.earnings_report.flow.hydrate",
            return_value=[],
        ):
            result = EarningsReportEngine().run({})
        assert set(result.keys()) == {
            "status", "data", "meta", "error",
        }
        assert result["status"] == "success"
        assert result["meta"]["engine"] == "earnings_report"

    def test_none_input_returns_success(self):
        with patch(
            "engines.earnings_report.flow.hydrate",
            return_value=[],
        ):
            result = EarningsReportEngine().run(None)
        assert result["status"] == "success"

    def test_non_dict_input_returns_error(self):
        result = EarningsReportEngine().run("not a dict")
        assert result["status"] == "error"


# ── End-to-end ──────────────────────────────────────────────


class TestEngineEndToEnd:
    def test_supplied_orders_bypass_hydrator(self):
        orders = [
            {
                "created_at": _iso_at(-2, time.time()),
                "total_price": 100.0,
                "currency_code": "USD",
            },
        ]
        result = EarningsReportEngine().run({
            "data": {"orders": orders, "window_hours": 24.0},
        })
        assert result["data"]["current"]["revenue"] == 100.0
        assert result["data"]["verdict"] == "earning"

    def test_negative_window_hours_returns_error(self):
        result = EarningsReportEngine().run({
            "data": {"window_hours": -1.0},
        })
        assert result["status"] == "error"

    def test_huge_window_clamped(self):
        with patch(
            "engines.earnings_report.flow.hydrate",
            return_value=[],
        ):
            result = EarningsReportEngine().run({
                "data": {"window_hours": 99999.0},
            })
        # MAX_WINDOW_HOURS = 24 * 90 = 2160
        assert result["data"]["window_hours"] <= 2160.0

    def test_non_numeric_window_returns_error(self):
        result = EarningsReportEngine().run({
            "data": {"window_hours": "many"},
        })
        assert result["status"] == "error"


# ── to_dict serialization ──────────────────────────────────


class TestToDict:
    def test_round_trip_shape(self):
        r = EarningsReport(
            store_id="store-a", window_hours=24.0,
            current=WindowSummary(revenue=100.0, order_count=1),
            previous=WindowSummary(),
            delta=100.0, delta_pct=100.0, verdict="earning",
        )
        d = to_dict(r)
        assert d["store_id"] == "store-a"
        assert d["current"]["revenue"] == 100.0
        assert d["verdict"] == "earning"
