"""Tests for engines.revenue_reconciliation — W963-47."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from engines.revenue_reconciliation import (
    RevenueReconciliationEngine,
)
from engines.revenue_reconciliation.reconciler import (
    FleetRecon,
    OrphanAction,
    StoreRecon,
    _is_revenue_driving,
    _matches_order,
    _order_total,
    _parse_iso,
    reconcile_fleet,
    reconcile_store,
)


def _make_action(
    aid="a1",
    engine="loyalty",
    action_type="mint_code",
    decided_at=None,
):
    a = MagicMock()
    a.id = aid
    a.engine = engine
    a.action_type = action_type
    a.decided_at = decided_at
    return a


def _make_order(
    oid="o1",
    minutes_ago=60.0,
    total="100.00",
    cancelled=False,
):
    now = datetime.now(timezone.utc)
    created = now - timedelta(minutes=minutes_ago)
    return {
        "id": oid,
        "created_at": created.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
        ),
        "total_price": total,
        "cancelled_at": (
            "2024-01-01" if cancelled else None
        ),
    }


# ── helpers ───────────────────────────────────────────────


class TestParseIso:
    def test_iso_string(self):
        dt = _parse_iso("2026-06-04T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_unix_float(self):
        assert _parse_iso(1780000000.0) is not None

    def test_datetime(self):
        d = datetime(2026, 6, 4, tzinfo=timezone.utc)
        assert _parse_iso(d) == d

    def test_naive_datetime_gets_utc(self):
        d = datetime(2026, 6, 4)
        out = _parse_iso(d)
        assert out.tzinfo is not None

    def test_garbage_returns_none(self):
        assert _parse_iso("xxx") is None
        assert _parse_iso(None) is None
        assert _parse_iso("") is None


class TestOrderTotal:
    def test_total_price(self):
        assert _order_total({"total_price": "50"}) == 50.0

    def test_fallback(self):
        assert _order_total({"subtotal_price": "10"}) == 10.0

    def test_garbage(self):
        assert _order_total({"total_price": "x"}) == 0.0


class TestIsRevenueDriving:
    def test_loyalty_engine(self):
        a = _make_action(engine="loyalty")
        assert _is_revenue_driving(a) is True

    def test_cart_recovery(self):
        a = _make_action(
            engine="cart_recovery", action_type="mint",
        )
        assert _is_revenue_driving(a) is True

    def test_keyword_in_action_type(self):
        a = _make_action(
            engine="generic_writer",
            action_type="cart_recovery_send",
        )
        assert _is_revenue_driving(a) is True

    def test_non_driving_engine(self):
        a = _make_action(
            engine="catalog_quality",
            action_type="tag_product",
        )
        assert _is_revenue_driving(a) is False


class TestMatchesOrder:
    def test_action_before_order_in_window(self):
        decided = datetime.now(timezone.utc) - timedelta(
            hours=10,
        )
        order = datetime.now(timezone.utc) - timedelta(
            hours=2,
        )
        assert _matches_order(
            decided, order, window_hours=48.0,
        ) is True

    def test_action_after_order_skipped(self):
        decided = datetime.now(timezone.utc) - timedelta(
            hours=2,
        )
        order = datetime.now(timezone.utc) - timedelta(
            hours=10,
        )
        assert _matches_order(
            decided, order, window_hours=48.0,
        ) is False

    def test_outside_window(self):
        decided = datetime.now(timezone.utc) - timedelta(
            hours=100,
        )
        order = datetime.now(timezone.utc) - timedelta(
            hours=1,
        )
        assert _matches_order(
            decided, order, window_hours=48.0,
        ) is False


# ── reconcile_store ───────────────────────────────────────


class TestReconcileStore:
    def test_no_data(self):
        r = reconcile_store(
            store_id="s1",
            executed_override=[],
            orders_override=[],
        )
        assert r.store_id == "s1"
        assert r.order_count == 0
        assert r.attributed_order_count == 0
        assert r.organic_order_count == 0
        assert r.attribution_pct == 0.0

    def test_organic_only(self):
        order = _make_order(minutes_ago=30.0)
        r = reconcile_store(
            store_id="s1",
            executed_override=[],
            orders_override=[order],
        )
        assert r.order_count == 1
        assert r.organic_order_count == 1
        assert r.attributed_order_count == 0
        assert r.organic_revenue == 100.0

    def test_attributed_match(self):
        # Action 4h ago, order 2h ago → match
        decided = (
            datetime.now(timezone.utc) - timedelta(hours=4)
        ).timestamp()
        action = _make_action(decided_at=decided)
        order = _make_order(minutes_ago=120.0)
        r = reconcile_store(
            store_id="s1",
            executed_override=[action],
            orders_override=[order],
        )
        assert r.order_count == 1
        assert r.attributed_order_count == 1
        assert r.attributed_revenue == 100.0
        assert r.attribution_pct == 100.0

    def test_orphan_action(self):
        # Action 2h ago, no orders → orphan
        decided = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).timestamp()
        action = _make_action(
            decided_at=decided, engine="cart_recovery",
        )
        r = reconcile_store(
            store_id="s1",
            executed_override=[action],
            orders_override=[],
        )
        assert r.orphan_action_count == 1
        assert isinstance(r.orphans[0], OrphanAction)
        assert r.orphans[0].engine == "cart_recovery"

    def test_non_driving_action_not_orphaned(self):
        # Tag-product action shouldn't orphan
        decided = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).timestamp()
        action = _make_action(
            decided_at=decided,
            engine="catalog_quality",
            action_type="tag_product",
        )
        r = reconcile_store(
            store_id="s1",
            executed_override=[action],
            orders_override=[],
        )
        assert r.orphan_action_count == 0

    def test_cancelled_orders_skipped(self):
        order = _make_order(
            minutes_ago=30.0, cancelled=True,
        )
        r = reconcile_store(
            store_id="s1",
            executed_override=[],
            orders_override=[order],
        )
        assert r.order_count == 0

    def test_window_boundary(self):
        # Action 50h ago, order 2h ago, window=48h → too old
        decided = (
            datetime.now(timezone.utc)
            - timedelta(hours=51)
        ).timestamp()
        action = _make_action(decided_at=decided)
        order = _make_order(minutes_ago=120.0)
        r = reconcile_store(
            store_id="s1",
            days=7,
            attribution_window_hours=48.0,
            executed_override=[action],
            orders_override=[order],
        )
        # Order is organic (action outside window)
        assert r.organic_order_count == 1
        assert r.attributed_order_count == 0


# ── reconcile_fleet ───────────────────────────────────────


class TestReconcileFleet:
    def test_with_store_filter(self):
        r = reconcile_fleet(
            store_filter="s1",
        )
        assert isinstance(r, FleetRecon)
        # Only one store
        assert len(r.by_store) <= 1

    def test_fleet_pct_computation(self):
        # Patch _list_fleet_stores to return controlled set
        from engines.revenue_reconciliation import (
            reconciler as rmod,
        )
        from unittest.mock import patch

        decided = (
            datetime.now(timezone.utc) - timedelta(hours=4)
        ).timestamp()
        action = _make_action(decided_at=decided)
        order_attr = _make_order(
            oid="o1", minutes_ago=120.0, total="100",
        )
        order_org = _make_order(
            oid="o2", minutes_ago=30.0, total="200",
        )

        # Override reconcile_store via monkeypatching the
        # imported function in module
        def fake_reconcile_store(*, store_id, **kw):
            if store_id == "sA":
                return reconcile_store(
                    store_id="sA",
                    executed_override=[action],
                    orders_override=[order_attr],
                )
            return reconcile_store(
                store_id="sB",
                executed_override=[],
                orders_override=[order_org],
            )

        with patch.object(
            rmod, "_list_fleet_stores",
            return_value=["sA", "sB"],
        ), patch.object(
            rmod, "reconcile_store",
            side_effect=fake_reconcile_store,
        ):
            r = reconcile_fleet()
        # Sorted: sA (100 attributed) first
        assert r.by_store[0].store_id == "sA"
        # 100 / (100 + 200) = 33.3%
        assert abs(r.fleet_attribution_pct - 33.3) < 0.5
        assert r.fleet_attributed_revenue == 100.0
        assert r.fleet_organic_revenue == 200.0


# ── Envelope (Pattern Q) ──────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = RevenueReconciliationEngine().run({})
        assert r["status"] == "success"
        assert "data" in r
        assert "meta" in r
        assert "error" in r

    def test_none_success(self):
        r = RevenueReconciliationEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = RevenueReconciliationEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = RevenueReconciliationEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = RevenueReconciliationEngine().run({})
        assert (
            r["meta"]["engine"] == "revenue_reconciliation"
        )

    def test_single_mode(self):
        r = RevenueReconciliationEngine().run({
            "data": {"store_id": "sX", "days": 3},
        })
        assert r["status"] == "success"
        assert r["data"]["mode"] == "single"
        assert r["data"]["store_id"] == "sX"

    def test_invalid_days_falls_back(self):
        r = RevenueReconciliationEngine().run({
            "data": {"days": "abc"},
        })
        assert r["status"] == "success"
        assert r["data"]["days"] == 7

    def test_invalid_window_falls_back(self):
        r = RevenueReconciliationEngine().run({
            "data": {"attribution_window_hours": "xyz"},
        })
        assert r["status"] == "success"
        assert r["data"]["attribution_window_hours"] == 48.0

    def test_next_action_present(self):
        r = RevenueReconciliationEngine().run({})
        assert "next_action" in r["data"]
        assert r["data"]["next_action"]
