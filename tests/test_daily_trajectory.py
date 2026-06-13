"""Tests for engines.daily_trajectory — W963-24."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engines.daily_trajectory import DailyTrajectoryEngine
from engines.daily_trajectory.analyzer import (
    DayBucket,
    _compute_verdict_and_slope,
    _order_total,
    _parse_iso,
    analyze_trajectory,
    render_sparkline,
)


# ── _parse_iso ────────────────────────────────────────────


class TestParseIso:
    def test_z_suffix(self):
        dt = _parse_iso("2026-06-04T12:00:00Z")
        assert dt is not None
        assert dt.year == 2026 and dt.month == 6

    def test_with_offset(self):
        dt = _parse_iso("2026-06-04T12:00:00+02:00")
        assert dt is not None

    def test_date_only(self):
        dt = _parse_iso("2026-06-04")
        assert dt is not None

    def test_space_separator(self):
        dt = _parse_iso("2026-06-04 12:00:00Z")
        assert dt is not None

    def test_garbage_returns_none(self):
        assert _parse_iso("not-a-date") is None

    def test_empty_returns_none(self):
        assert _parse_iso("") is None

    def test_non_string_returns_none(self):
        assert _parse_iso(None) is None
        assert _parse_iso(123) is None


# ── _order_total ──────────────────────────────────────────


class TestOrderTotal:
    def test_total_price_key(self):
        assert _order_total({"total_price": "42.50"}) == 42.5

    def test_fallback_to_current_total_price(self):
        assert _order_total({
            "current_total_price": "10.00",
        }) == 10.0

    def test_no_total_returns_zero(self):
        assert _order_total({}) == 0.0

    def test_garbage_returns_zero(self):
        assert _order_total({"total_price": "abc"}) == 0.0

    def test_numeric(self):
        assert _order_total({"total_price": 25}) == 25.0


# ── _compute_verdict_and_slope ────────────────────────────


def _make_buckets(revenues: list[float]) -> list[DayBucket]:
    out = []
    for i, r in enumerate(revenues):
        out.append(
            DayBucket(
                date=f"2026-06-{i+1:02d}",
                order_count=1 if r > 0 else 0,
                revenue=r,
            )
        )
    return out


class TestComputeVerdict:
    def test_too_few_buckets_cold_start(self):
        bs = _make_buckets([0.0, 100.0])
        v, _ = _compute_verdict_and_slope(bs)
        assert v == "cold_start"

    def test_all_zero_cold_start(self):
        bs = _make_buckets([0.0] * 10)
        v, _ = _compute_verdict_and_slope(bs)
        assert v == "cold_start"

    def test_rising(self):
        bs = _make_buckets(
            [10, 10, 10, 10, 100, 100, 100, 100],
        )
        v, slope = _compute_verdict_and_slope(bs)
        assert v == "rising"
        assert slope > 100.0

    def test_declining(self):
        bs = _make_buckets(
            [100, 100, 100, 100, 10, 10, 10, 10],
        )
        v, slope = _compute_verdict_and_slope(bs)
        assert v == "declining"
        assert slope < -50.0

    def test_flat(self):
        bs = _make_buckets(
            [50, 52, 48, 51, 49, 50, 51, 52],
        )
        v, slope = _compute_verdict_and_slope(bs)
        assert v == "flat"
        assert -15.0 < slope < 15.0


# ── render_sparkline ──────────────────────────────────────


class TestSparkline:
    def test_empty(self):
        assert render_sparkline([]) == ""

    def test_all_zero(self):
        bs = _make_buckets([0.0] * 5)
        spark = render_sparkline(bs)
        assert len(spark) == 5
        # All chars same (lowest in the chars set)
        assert spark[0] == " "

    def test_varied_revenues(self):
        bs = _make_buckets([10, 50, 100, 50, 10])
        spark = render_sparkline(bs)
        assert len(spark) == 5
        # Middle char should be highest
        assert spark[2] == "#"


# ── analyze_trajectory ─────────────────────────────────────


class TestAnalyze:
    def test_no_orders_cold_start(self):
        r = analyze_trajectory(days=7, orders=[])
        assert r.verdict == "cold_start"
        assert r.total_orders == 0
        assert r.total_revenue == 0.0
        assert len(r.buckets) == 7

    def test_orders_outside_window_ignored(self):
        old_order = {
            "id": "1", "total_price": "50",
            "created_at": (
                datetime.now(timezone.utc) - timedelta(days=100)
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        r = analyze_trajectory(
            days=7, orders=[old_order],
        )
        assert r.total_orders == 0

    def test_cancelled_orders_excluded(self):
        order = {
            "id": "1", "total_price": "50",
            "created_at": datetime.now(
                timezone.utc,
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cancelled_at": "2026-06-01T00:00:00Z",
        }
        r = analyze_trajectory(days=7, orders=[order])
        assert r.total_orders == 0

    def test_in_window_order_counted(self):
        order = {
            "id": "1", "total_price": "50",
            "created_at": (
                datetime.now(timezone.utc) - timedelta(days=2)
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        r = analyze_trajectory(days=7, orders=[order])
        assert r.total_orders == 1
        assert r.total_revenue == 50.0

    def test_days_clamped(self):
        r = analyze_trajectory(days=999, orders=[])
        assert r.days == 90

    def test_days_floor(self):
        r = analyze_trajectory(days=0, orders=[])
        assert r.days == 2


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = DailyTrajectoryEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = DailyTrajectoryEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = DailyTrajectoryEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = DailyTrajectoryEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = DailyTrajectoryEngine().run({})
        assert r["meta"]["engine"] == "daily_trajectory"


class TestEngineActions:
    def test_invalid_days_defaults_to_30(self):
        r = DailyTrajectoryEngine().run({
            "data": {"days": "abc"},
        })
        assert r["data"]["days"] == 30

    def test_store_id_threaded(self):
        r = DailyTrajectoryEngine().run({
            "data": {"store_id": "main"},
        })
        assert r["data"]["store_id"] == "main"

    def test_sparkline_present(self):
        r = DailyTrajectoryEngine().run({
            "data": {"days": 7},
        })
        assert "sparkline" in r["data"]
        assert len(r["data"]["sparkline"]) == 7

    def test_buckets_match_days(self):
        r = DailyTrajectoryEngine().run({
            "data": {"days": 14},
        })
        assert len(r["data"]["buckets"]) == 14
