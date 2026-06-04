"""Tests for engines.conversion_funnel — W963-25."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engines.conversion_funnel import ConversionFunnelEngine
from engines.conversion_funnel.analyzer import (
    _compute_stages,
    _identify_weakest,
    _next_action_for,
    _parse_iso,
    _verdict_for,
    analyze_funnel,
)


# ── _parse_iso ────────────────────────────────────────────


class TestParseIso:
    def test_z(self):
        assert _parse_iso("2026-06-04T12:00:00Z") is not None

    def test_offset(self):
        assert _parse_iso(
            "2026-06-04T12:00:00+02:00",
        ) is not None

    def test_space_separator(self):
        assert _parse_iso(
            "2026-06-04 12:00:00Z",
        ) is not None

    def test_date_only(self):
        assert _parse_iso("2026-06-04") is not None

    def test_garbage(self):
        assert _parse_iso("not-a-date") is None

    def test_none(self):
        assert _parse_iso(None) is None
        assert _parse_iso("") is None


# ── _compute_stages ──────────────────────────────────────


class TestComputeStages:
    def test_all_stages_present(self):
        s = _compute_stages(
            sessions=1000, cart_adds=80,
            checkouts_started=40, checkouts_completed=20,
        )
        assert len(s) == 4
        assert [x.name for x in s] == [
            "sessions", "cart_adds",
            "checkouts_started", "checkouts_completed",
        ]

    def test_no_sessions(self):
        s = _compute_stages(
            sessions=None, cart_adds=None,
            checkouts_started=10, checkouts_completed=5,
        )
        assert len(s) == 2
        assert [x.name for x in s] == [
            "checkouts_started", "checkouts_completed",
        ]

    def test_zero_sessions_omitted(self):
        # Sessions=0 means no traffic data — treat as missing.
        s = _compute_stages(
            sessions=0, cart_adds=None,
            checkouts_started=5, checkouts_completed=2,
        )
        names = [x.name for x in s]
        assert "sessions" not in names

    def test_conversion_computed(self):
        s = _compute_stages(
            sessions=1000, cart_adds=100,
            checkouts_started=50, checkouts_completed=25,
        )
        cart = s[1]
        assert abs(cart.conversion_from_prev - 0.1) < 0.001
        assert abs(cart.drop_rate - 0.9) < 0.001

    def test_checkout_completed_uses_started_as_prev(self):
        s = _compute_stages(
            sessions=None, cart_adds=None,
            checkouts_started=10, checkouts_completed=4,
        )
        assert s[1].name == "checkouts_completed"
        assert abs(s[1].conversion_from_prev - 0.4) < 0.001


# ── _identify_weakest ────────────────────────────────────


class TestWeakest:
    def test_empty(self):
        assert _identify_weakest([]) == ("", 0.0)

    def test_picks_largest_drop(self):
        s = _compute_stages(
            sessions=1000, cart_adds=900,
            checkouts_started=100, checkouts_completed=80,
        )
        # session->cart: 10% drop
        # cart->checkouts_started: ~89% drop  <- weakest
        # checkouts_started->completed: 20% drop
        name, drop = _identify_weakest(s)
        assert name == "checkouts_started"
        assert drop > 0.85


# ── _verdict_for ─────────────────────────────────────────


class TestVerdict:
    def test_no_traffic(self):
        assert _verdict_for(0, 0, 0.0) == "no_traffic"

    def test_leaky_when_started_zero_completed(self):
        assert _verdict_for(0, 10, 1.0) == "leaky"

    def test_leaky_when_huge_drop(self):
        assert _verdict_for(1, 10, 0.9) == "leaky"

    def test_healthy(self):
        assert _verdict_for(10, 12, 0.2) == "healthy"


# ── _next_action_for ──────────────────────────────────────


class TestNextActionFor:
    def test_no_traffic_drills_earn_bootstrap(self):
        s = _next_action_for("", 0, "no_traffic")
        assert "earn-bootstrap" in s

    def test_checkout_paid_drills_cart_recovery(self):
        s = _next_action_for(
            "checkouts_completed", 0.5, "leaky",
        )
        assert "cart_recovery" in s

    def test_product_checkout_drills_cro(self):
        s = _next_action_for(
            "checkouts_started", 0.8, "leaky",
        )
        assert "cro" in s.lower()

    def test_healthy_with_no_weakest_drills_reinvest(self):
        # When verdict=healthy AND weakest_link is empty
        # (no per-stage drop signal), falls through to the
        # generic "reinvest" recommendation.
        s = _next_action_for("", 0.0, "healthy")
        assert "ads" in s.lower() or "reinvest" in s.lower()


# ── analyze_funnel ────────────────────────────────────────


def _make_order(
    days_ago: float = 1.0,
    cancelled: bool = False,
):
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=days_ago)
    return {
        "id": "o1",
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cancelled_at": "2024-01-01" if cancelled else None,
    }


def _make_abandoned(days_ago: float = 1.0):
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=days_ago)
    return {
        "id": "ab1",
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


class TestAnalyzeFunnel:
    def test_no_orders_no_traffic(self):
        r = analyze_funnel(days=7, orders=[], abandoned=[])
        assert r.verdict == "no_traffic"

    def test_completed_no_abandoned_healthy(self):
        orders = [_make_order(1.0) for _ in range(3)]
        r = analyze_funnel(
            days=7, orders=orders, abandoned=[],
        )
        assert r.verdict == "healthy"

    def test_abandoned_without_completed_is_leaky(self):
        abandoned = [_make_abandoned(1.0) for _ in range(5)]
        r = analyze_funnel(
            days=7, orders=[], abandoned=abandoned,
        )
        assert r.verdict == "leaky"

    def test_cancelled_orders_excluded(self):
        orders = [_make_order(1.0, cancelled=True)]
        r = analyze_funnel(
            days=7, orders=orders, abandoned=[],
        )
        assert r.stages[-1].count == 0

    def test_days_clamped(self):
        r = analyze_funnel(days=999, orders=[], abandoned=[])
        assert r.days == 90

    def test_days_floor(self):
        r = analyze_funnel(days=0, orders=[], abandoned=[])
        assert r.days == 1

    def test_with_sessions_includes_session_stage(self):
        r = analyze_funnel(
            days=7, orders=[], abandoned=[],
            sessions=100, cart_adds=10,
        )
        names = [s.name for s in r.stages]
        assert "sessions" in names
        assert "cart_adds" in names


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = ConversionFunnelEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = ConversionFunnelEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = ConversionFunnelEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = ConversionFunnelEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = ConversionFunnelEngine().run({})
        assert r["meta"]["engine"] == "conversion_funnel"


class TestEngineActions:
    def test_invalid_days_defaults_to_7(self):
        r = ConversionFunnelEngine().run({
            "data": {"days": "abc"},
        })
        assert r["data"]["days"] == 7

    def test_store_id_threaded(self):
        r = ConversionFunnelEngine().run({
            "data": {"store_id": "main"},
        })
        assert r["data"]["store_id"] == "main"

    def test_stages_present(self):
        r = ConversionFunnelEngine().run({
            "data": {"orders": [], "abandoned": []},
        })
        stages = r["data"]["stages"]
        assert isinstance(stages, list)
        assert len(stages) >= 2

    def test_sessions_non_numeric_falls_back_to_none(self):
        r = ConversionFunnelEngine().run({
            "data": {
                "sessions": "abc",
                "orders": [], "abandoned": [],
            },
        })
        # No "sessions" stage when sessions is unparseable.
        names = [s["name"] for s in r["data"]["stages"]]
        assert "sessions" not in names
