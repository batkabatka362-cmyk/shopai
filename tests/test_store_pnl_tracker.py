"""Tests for engines.store_pnl_tracker — W963-45."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from engines.store_pnl_tracker import StorePnlTrackerEngine
from engines.store_pnl_tracker.tracker import (
    _action_cost,
    _order_refund_total,
    _order_shipping_cost,
    _order_total,
    _parse_iso,
    _verdict_for,
    StorePnl,
    compute_fleet_pnl,
    compute_store_pnl,
)


def _make_order(
    days_ago=1.0,
    total="100.00",
    cancelled=False,
    refunds=None,
    shipping=None,
):
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=days_ago)
    return {
        "id": "o1",
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_price": total,
        "cancelled_at": (
            "2024-01-01" if cancelled else None
        ),
        "refunds": refunds or [],
        "shipping_lines": shipping or [],
    }


def _make_action(
    aid="a1",
    engine="ads_launcher",
    action_type="launch_campaign",
    decided_at=None,
    params=None,
    result=None,
):
    a = MagicMock()
    a.id = aid
    a.engine = engine
    a.action_type = action_type
    a.decided_at = (
        decided_at
        if decided_at is not None
        else (
            datetime.now(timezone.utc)
            - timedelta(days=1)
        ).timestamp()
    )
    a.params = params or {}
    a.result = result or {}
    return a


# ── _order_total / _order_refund_total / _order_shipping ──


class TestOrderHelpers:
    def test_order_total(self):
        assert _order_total({"total_price": "50"}) == 50.0

    def test_order_refund_total(self):
        order = {
            "refunds": [
                {"transactions": [
                    {"amount": "20.00"},
                    {"amount": "10.00"},
                ]},
            ],
        }
        assert _order_refund_total(order) == 30.0

    def test_order_refund_total_invalid(self):
        # Garbage data shouldn't crash
        assert _order_refund_total({"refunds": "nope"}) == 0.0
        assert _order_refund_total({}) == 0.0

    def test_order_shipping_cost(self):
        order = {
            "shipping_lines": [
                {"price": "5.00"},
                {"price": "3.00"},
            ],
        }
        assert _order_shipping_cost(order) == 8.0

    def test_order_shipping_invalid(self):
        assert _order_shipping_cost({}) == 0.0


# ── _action_cost ──────────────────────────────────────────


class TestActionCost:
    def test_result_cost(self):
        action = _make_action(
            result={"cost": "25.00"},
        )
        assert _action_cost(action) == 25.0

    def test_params_daily_budget(self):
        action = _make_action(
            params={"daily_budget_usd": "10"},
        )
        assert _action_cost(action) == 10.0

    def test_no_cost(self):
        action = _make_action()
        assert _action_cost(action) == 0.0

    def test_garbage(self):
        action = _make_action(
            params={"cost": "not-a-number"},
        )
        assert _action_cost(action) == 0.0


# ── _verdict_for ─────────────────────────────────────────


class TestVerdict:
    def test_no_data(self):
        pnl = StorePnl(store_id="s", days=7)
        assert _verdict_for(pnl) == "no_data"

    def test_profitable(self):
        pnl = StorePnl(
            store_id="s", days=7,
            gross_revenue=200, gross_profit=50,
            total_cost=100,
        )
        assert _verdict_for(pnl) == "profitable"

    def test_loss(self):
        pnl = StorePnl(
            store_id="s", days=7,
            gross_revenue=50, gross_profit=-100,
            total_cost=150,
        )
        assert _verdict_for(pnl) == "loss"

    def test_break_even(self):
        pnl = StorePnl(
            store_id="s", days=7,
            gross_revenue=100, gross_profit=0.5,
            total_cost=100,
        )
        assert _verdict_for(pnl) == "break_even"


# ── compute_store_pnl ─────────────────────────────────────


class TestComputeStorePnl:
    def test_no_orders_no_costs(self):
        pnl = compute_store_pnl(
            store_id="s1", days=7,
            orders_override=[], executed_override=[],
        )
        assert pnl.gross_revenue == 0.0
        assert pnl.total_cost == 0.0
        assert pnl.verdict == "no_data"

    def test_revenue_counted(self):
        orders = [_make_order(days_ago=1.0, total="100")]
        pnl = compute_store_pnl(
            store_id="s1", days=7,
            orders_override=orders,
            executed_override=[],
        )
        assert pnl.gross_revenue == 100.0
        assert pnl.order_count == 1

    def test_cancelled_excluded(self):
        orders = [_make_order(cancelled=True, total="100")]
        pnl = compute_store_pnl(
            store_id="s1", days=7,
            orders_override=orders,
            executed_override=[],
        )
        assert pnl.gross_revenue == 0.0
        assert pnl.order_count == 0

    def test_out_of_window_excluded(self):
        orders = [_make_order(days_ago=100.0, total="100")]
        pnl = compute_store_pnl(
            store_id="s1", days=7,
            orders_override=orders,
            executed_override=[],
        )
        assert pnl.order_count == 0

    def test_refunds_subtract(self):
        order = _make_order(
            total="100",
            refunds=[{
                "transactions": [{"amount": "20"}],
            }],
        )
        pnl = compute_store_pnl(
            store_id="s1", days=7,
            orders_override=[order],
            executed_override=[],
        )
        assert pnl.refunds == 20.0
        assert pnl.net_revenue == 80.0

    def test_ad_spend_action_counted(self):
        action = _make_action(
            action_type="launch_campaign",
            params={"daily_budget_usd": "20"},
        )
        pnl = compute_store_pnl(
            store_id="s1", days=7,
            orders_override=[],
            executed_override=[action],
        )
        assert pnl.ad_spend == 20.0

    def test_esp_action_counted_per_send(self):
        action = _make_action(
            engine="welcome_series",
            action_type="send_welcome_email",
        )
        pnl = compute_store_pnl(
            store_id="s1", days=7,
            orders_override=[],
            executed_override=[action],
        )
        assert pnl.esp_spend > 0.0

    def test_profit_computed(self):
        orders = [_make_order(total="200")]
        action = _make_action(
            action_type="launch_campaign",
            params={"daily_budget_usd": "50"},
        )
        pnl = compute_store_pnl(
            store_id="s1", days=7,
            orders_override=orders,
            executed_override=[action],
        )
        assert pnl.gross_revenue == 200.0
        assert pnl.ad_spend == 50.0
        assert pnl.gross_profit == 150.0  # 200 - 50

    def test_margin_pct(self):
        orders = [_make_order(total="100")]
        pnl = compute_store_pnl(
            store_id="s1", days=7,
            orders_override=orders,
            executed_override=[],
        )
        assert pnl.margin_pct == 100.0


# ── compute_fleet_pnl ─────────────────────────────────────


class TestComputeFleetPnl:
    def test_empty_fleet(self):
        with patch(
            "engines.store_pnl_tracker.tracker."
            "_list_fleet_stores",
            return_value=[],
        ):
            r = compute_fleet_pnl(days=7)
        assert len(r.by_store) == 0

    def test_aggregates_across_stores(self):
        with patch(
            "engines.store_pnl_tracker.tracker."
            "_list_fleet_stores",
            return_value=["s1", "s2"],
        ), patch(
            "engines.store_pnl_tracker.tracker."
            "_hydrate_orders",
            return_value=[_make_order(total="100")],
        ), patch(
            "engines.store_pnl_tracker.tracker."
            "_list_executed",
            return_value=[],
        ):
            r = compute_fleet_pnl(days=7)
        assert len(r.by_store) == 2
        assert r.fleet_revenue == 200.0

    def test_store_exception_isolated(self):
        # If one store raises, others still computed
        call_count = {"n": 0}
        def _flaky(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("store 2 broke")
            return [_make_order(total="100")]
        with patch(
            "engines.store_pnl_tracker.tracker."
            "_list_fleet_stores",
            return_value=["s1", "s2", "s3"],
        ), patch(
            "engines.store_pnl_tracker.tracker."
            "_hydrate_orders",
            side_effect=_flaky,
        ), patch(
            "engines.store_pnl_tracker.tracker."
            "_list_executed",
            return_value=[],
        ):
            r = compute_fleet_pnl(days=7)
        # s2 dropped
        assert len(r.by_store) == 2

    def test_store_filter_short_circuits(self):
        with patch(
            "engines.store_pnl_tracker.tracker."
            "_list_fleet_stores",
            return_value=["s1", "s2", "s3"],
        ) as list_mock, patch(
            "engines.store_pnl_tracker.tracker."
            "_hydrate_orders",
            return_value=[],
        ), patch(
            "engines.store_pnl_tracker.tracker."
            "_list_executed",
            return_value=[],
        ):
            r = compute_fleet_pnl(
                days=7, store_filter="onlyme",
            )
        assert not list_mock.called
        assert len(r.by_store) == 1
        assert r.by_store[0].store_id == "onlyme"


# ── W963-99: per-store active_store wrap ──────────────────


class TestPerStoreActiveStore:
    """W963-99: tracker.py shares the same hydrate bug as
    revenue_reconciliation. _hydrate_orders(store_id) wraps
    in active_store(sid) so adapter router can scope creds."""

    def test_hydrate_runs_under_active_store_context(self):
        from unittest.mock import patch
        from engines.store_pnl_tracker import tracker

        captured = {"sid": "MISSING"}

        def fake_hydrate(*, supplied, capability_name,
                         list_field, limit):
            from core.context import get_active_store_id
            captured["sid"] = get_active_store_id()
            return []

        with patch(
            "engines._shopify_hydrator.hydrate",
            side_effect=fake_hydrate,
        ):
            tracker._hydrate_orders("store_b", limit=10)

        assert captured["sid"] == "store_b"

    def test_empty_store_id_uses_nullcontext(self):
        from unittest.mock import patch
        from engines.store_pnl_tracker import tracker

        captured = {"sid": "MISSING"}

        def fake_hydrate(*, supplied, capability_name,
                         list_field, limit):
            from core.context import get_active_store_id
            captured["sid"] = get_active_store_id()
            return []

        with patch(
            "engines._shopify_hydrator.hydrate",
            side_effect=fake_hydrate,
        ):
            tracker._hydrate_orders("", limit=10)

        assert captured["sid"] is None


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = StorePnlTrackerEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = StorePnlTrackerEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = StorePnlTrackerEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = StorePnlTrackerEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = StorePnlTrackerEngine().run({})
        assert r["meta"]["engine"] == "store_pnl_tracker"


class TestEngineActions:
    def test_fleet_mode_default(self):
        r = StorePnlTrackerEngine().run({})
        assert r["data"]["mode"] == "fleet"

    def test_single_mode_when_store_id(self):
        with patch(
            "engines.store_pnl_tracker.tracker."
            "_hydrate_orders",
            return_value=[],
        ), patch(
            "engines.store_pnl_tracker.tracker."
            "_list_executed",
            return_value=[],
        ):
            r = StorePnlTrackerEngine().run({
                "data": {"store_id": "X"},
            })
        assert r["data"]["mode"] == "single"
        assert r["data"]["store_id"] == "X"

    def test_invalid_days_falls_back(self):
        r = StorePnlTrackerEngine().run({
            "data": {"days": "abc"},
        })
        assert r["data"]["days"] == 7

    def test_days_threaded(self):
        r = StorePnlTrackerEngine().run({
            "data": {"days": 30},
        })
        assert r["data"]["days"] == 30


# ── W963-94: sign-prefix-before-$ rendering ───────────────


class TestSignPrefixRendering:
    """W963-94 regression: pre-fix, single + fleet loss
    renderers showed $-50.00 instead of -$50.00."""

    def test_single_loss_renders_minus_dollar(self):
        from engines.store_pnl_tracker.flow import (
            _single_next_action,
        )
        pnl = StorePnl(
            store_id="s1", days=7,
            gross_profit=-50.0, verdict="loss",
        )
        out = _single_next_action(pnl)
        assert "-$50.00" in out
        assert "$-50" not in out

    def test_single_profitable_unchanged(self):
        from engines.store_pnl_tracker.flow import (
            _single_next_action,
        )
        pnl = StorePnl(
            store_id="s1", days=7,
            gross_profit=120.0, margin_pct=25.0,
            verdict="profitable",
        )
        out = _single_next_action(pnl)
        assert "$120.00" in out
        assert "-$120" not in out

    def test_fleet_loss_renders_minus_dollar(self):
        from engines.store_pnl_tracker.flow import (
            _fleet_next_action,
        )
        from engines.store_pnl_tracker.tracker import (
            FleetPnlReport,
        )
        report = FleetPnlReport(
            days=7, fleet_gross_profit=-80.0,
            by_store=[StorePnl(store_id="s1", days=7)],
        )
        out = _fleet_next_action(report)
        assert "-$80.00" in out
        assert "$-80" not in out

    def test_fleet_profitable_unchanged(self):
        from engines.store_pnl_tracker.flow import (
            _fleet_next_action,
        )
        from engines.store_pnl_tracker.tracker import (
            FleetPnlReport,
        )
        report = FleetPnlReport(
            days=7, fleet_gross_profit=200.0,
            fleet_margin_pct=30.0,
            by_store=[StorePnl(store_id="s1", days=7)],
        )
        out = _fleet_next_action(report)
        assert "$200.00" in out
        assert "-$200" not in out
