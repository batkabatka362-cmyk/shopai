"""Order webhook → LTV + post-purchase email integration.

Verifies the wire-up added in ``core/webhooks/order_handler``:

  1. A paid order records into the budget_buyer LTV tracker —
     cumulative across repeat orders from the same customer.
  2. A paid order enrolls the buyer in the email_campaigns
     post_purchase flow.
  3. Gate-check synthetic orders skip BOTH hooks so they don't
     pollute production state during the `shopai ready-for-live`
     smoke run.
  4. Missing email / malformed customer doesn't crash the
     webhook path — handler recovers and still runs the other
     steps.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.engines.budget_buyer import (
    LTVTracker, BudgetBuyerEngine,
    reset_singleton_for_tests as _reset_bb,
)
from core.engines.email_campaigns import (
    EmailCampaignEngine, ScheduleQueue,
    reset_singleton_for_tests as _reset_ec,
)
from core.webhooks.order_handler import OrderWebhookHandler


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point both engines at tmp databases + register their
    singletons so the handler's lazy ``get_engine()`` lookups
    hit our isolated state."""
    _reset_bb()
    _reset_ec()

    tracker = LTVTracker(
        db_path=str(tmp_path / "ltv.db"),
        now_fn=lambda: 1_700_000_000.0,
    )
    bb_engine = BudgetBuyerEngine(
        ltv_tracker=tracker,
        now_fn=lambda: 1_700_000_000.0,
    )
    import core.engines.budget_buyer.engine as bb_mod
    bb_mod._SINGLETON = bb_engine

    email_q = ScheduleQueue(
        db_path=str(tmp_path / "email.db"),
        now_fn=lambda: 1_700_000_000.0,
    )
    ec_engine = EmailCampaignEngine(
        queue=email_q, from_email="hello@deguar.com",
        now_fn=lambda: 1_700_000_000.0,
    )
    import core.engines.email_campaigns.engine as ec_mod
    ec_mod._SINGLETON = ec_engine

    monkeypatch.setenv(
        "SHOPAI_SHOPIFY_URL", "deguar.myshopify.com",
    )
    monkeypatch.setenv("SHOPAI_STORE_NAME", "Deguar")

    yield {
        "handler": OrderWebhookHandler(),
        "ltv": tracker,
        "ec_queue": email_q,
        "ec_engine": ec_engine,
    }

    _reset_bb()
    _reset_ec()


def _order(
    *, email: str = "jane@example.com",
    total: str = "29.99",
    customer_id: str = "c_123",
    first_name: str = "Jane",
    product_title: str = "Galaxy Projector",
    is_gate_check: bool = False,
) -> dict:
    """Minimal Shopify-shaped order payload."""
    order: dict = {
        "id": 1234,
        "total_price": total,
        "email": email,
        "customer": {
            "id": customer_id, "email": email,
            "first_name": first_name,
        },
        "line_items": [
            {"title": product_title, "quantity": 1,
             "price": total},
        ],
        "note_attributes": [],
        "processed_at": "2026-04-22T10:30:00Z",
    }
    if is_gate_check:
        order["note_attributes"].append({
            "name": "shopai_gate_check", "value": "1",
        })
    return order


# ── LTV ingest ────────────────────────────────────────────


class TestLTVIngest:
    def test_first_order_records_customer(self, wired):
        wired["handler"].handle_order_paid(_order())
        ltv = wired["ltv"].get("c_123")
        assert ltv is not None
        assert ltv.orders_count == 1
        assert ltv.total_spent_usd == 29.99
        assert ltv.email == "jane@example.com"

    def test_repeat_order_accumulates(self, wired):
        h = wired["handler"]
        h.handle_order_paid(_order(total="20.00"))
        h.handle_order_paid(_order(total="50.00"))
        ltv = wired["ltv"].get("c_123")
        assert ltv.orders_count == 2
        assert ltv.total_spent_usd == 70.0

    def test_ts_parsed_from_processed_at(self, wired):
        """LTV first_order_at uses the order's processed_at,
        not the webhook arrival time."""
        wired["handler"].handle_order_paid(_order())
        ltv = wired["ltv"].get("c_123")
        # 2026-04-22T10:30:00Z → ~1745321400
        import datetime
        expected = datetime.datetime.fromisoformat(
            "2026-04-22T10:30:00+00:00",
        ).timestamp()
        assert abs(ltv.first_order_at - expected) < 2.0

    def test_guest_order_without_customer_id_uses_email(
        self, wired,
    ):
        """Shopify guest orders have no ``customer.id`` — we
        should still record LTV keyed by email."""
        order = _order(customer_id="")
        order["customer"]["id"] = None
        wired["handler"].handle_order_paid(order)
        ltv = wired["ltv"].get("jane@example.com")
        assert ltv is not None
        assert ltv.email == "jane@example.com"

    def test_missing_email_and_customer_no_crash(self, wired):
        """Pathological order with neither email nor customer.id
        → skip LTV, don't crash."""
        order = _order()
        order["customer"] = None
        order["email"] = ""
        recorded = wired["handler"].handle_order_paid(order)
        # Handler completes
        assert "order_id" in recorded
        # No LTV written
        assert wired["ltv"].get("jane@example.com") is None


# ── Post-purchase email enroll ──────────────────────────


class TestPostPurchaseEnroll:
    def test_enroll_queues_two_steps(self, wired):
        wired["handler"].handle_order_paid(_order())
        # post_purchase has 2 steps (3d + 14d)
        rows = wired["ec_engine"].list_for_recipient(
            "jane@example.com",
        )
        assert len(rows) == 2
        step_ids = {r.step_id for r in rows}
        assert step_ids == {
            "post_thank_you", "post_cross_sell",
        }

    def test_context_populated_from_order(self, wired):
        wired["handler"].handle_order_paid(_order(
            first_name="Jane", product_title="Galaxy Projector",
        ))
        rows = wired["ec_engine"].list_for_recipient(
            "jane@example.com",
        )
        first = next(
            r for r in rows if r.step_id == "post_thank_you"
        )
        ctx = first.context
        assert ctx["first_name"] == "Jane"
        assert ctx["product_name"] == "Galaxy Projector"
        assert ctx["store_name"] == "Deguar"
        assert "deguar.myshopify.com" in ctx["store_url"]

    def test_double_order_idempotent_enroll(self, wired):
        """Same customer ordering twice shouldn't duplicate the
        flow — engine's idempotency key
        (recipient × flow × step_id) prevents it."""
        h = wired["handler"]
        h.handle_order_paid(_order())
        h.handle_order_paid(_order())
        rows = wired["ec_engine"].list_for_recipient(
            "jane@example.com",
        )
        assert len(rows) == 2  # not 4

    def test_missing_email_skips_enroll(self, wired):
        order = _order()
        order["customer"] = None
        order["email"] = ""
        wired["handler"].handle_order_paid(order)
        # No enrollment (nothing to target)
        stats = wired["ec_engine"].stats()
        assert stats["totals"]["total"] == 0


# ── Gate-check skip ──────────────────────────────────────


class TestGateCheckSkip:
    def test_synth_order_does_not_record_ltv(self, wired):
        wired["handler"].handle_order_paid(
            _order(is_gate_check=True),
        )
        assert wired["ltv"].get("c_123") is None

    def test_synth_order_does_not_enroll_email(self, wired):
        wired["handler"].handle_order_paid(
            _order(is_gate_check=True),
        )
        stats = wired["ec_engine"].stats()
        assert stats["totals"]["total"] == 0


# ── Failure isolation ───────────────────────────────────


class TestFailureIsolation:
    def test_ltv_failure_does_not_break_webhook(self, wired):
        with patch(
            "core.engines.budget_buyer.get_engine",
            side_effect=RuntimeError("boom"),
        ):
            recorded = wired["handler"].handle_order_paid(
                _order(),
            )
        # Handler completed + order_id recorded
        assert recorded["order_id"]
        # ltv_recorded flagged false
        assert recorded.get("ltv_recorded") is False

    def test_email_failure_does_not_break_webhook(self, wired):
        with patch(
            "core.engines.email_campaigns.get_engine",
            side_effect=RuntimeError("engine down"),
        ):
            recorded = wired["handler"].handle_order_paid(
                _order(),
            )
        assert recorded["order_id"]
        assert recorded.get("post_purchase_enrolled") is False


# ── Timestamp parser ─────────────────────────────────────


class TestOrderTS:
    def test_parses_shopify_iso(self):
        from core.webhooks.order_handler import _order_ts
        ts = _order_ts({
            "processed_at": "2026-04-22T10:30:00Z",
        })
        assert ts > 1_700_000_000

    def test_falls_back_to_created_at(self):
        from core.webhooks.order_handler import _order_ts
        ts = _order_ts({
            "created_at": "2026-04-20T08:00:00+00:00",
        })
        assert ts > 1_700_000_000

    def test_missing_ts_returns_now(self):
        """No ts fields → fallback to current time (not zero)."""
        from core.webhooks.order_handler import _order_ts
        ts = _order_ts({})
        # Current time is roughly > 1_700_000_000 (late 2024+)
        assert ts > 1_700_000_000

    def test_garbage_ts_falls_back_to_now(self):
        from core.webhooks.order_handler import _order_ts
        ts = _order_ts({"processed_at": "not a date"})
        assert ts > 1_700_000_000
