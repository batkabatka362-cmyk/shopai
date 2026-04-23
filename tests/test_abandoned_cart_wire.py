"""Abandoned-cart webhook wire tests.

Covers:
  * Payload parsers (email / first_name / item_name / cart URL)
  * ``handle_checkout_update``:
      - happy path enrols all 2 steps
      - empty cart skips
      - no email yet skips (buyer hasn't reached that step)
      - already-completed checkout skips (order fired)
      - unsubscribed recipient returns skip_reason cleanly
      - idempotent on repeat webhooks
  * Cancel-on-order:
      - ``order_handler.handle_order_paid`` cancels pending
        abandoned_cart for the buyer
      - cancel only affects pending rows (sent/failed
        untouched)
      - no crash when buyer never abandoned a cart
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.engines.email_campaigns import (
    EmailCampaignEngine, ScheduleQueue, get_engine,
    reset_singleton_for_tests as _reset_ec,
)
from core.engines.budget_buyer import (
    LTVTracker, BudgetBuyerEngine,
    reset_singleton_for_tests as _reset_bb,
)
from core.webhooks.checkout_handler import (
    _build_cart_url, _extract_email, _extract_first_name,
    _extract_item_name, _is_completed,
    handle_checkout_update,
)
from core.webhooks.order_handler import OrderWebhookHandler


@pytest.fixture
def email_engine(tmp_path, monkeypatch):
    _reset_ec()
    q = ScheduleQueue(
        db_path=str(tmp_path / "email.db"),
        now_fn=lambda: 1_700_000_000.0,
    )
    e = EmailCampaignEngine(
        queue=q, from_email="hello@deguar.com",
        now_fn=lambda: 1_700_000_000.0,
    )
    # Register as singleton so handle_checkout_update picks
    # up OUR isolated engine rather than spawning a new one
    # on a production DB path.
    import core.engines.email_campaigns.engine as ec_mod
    ec_mod._SINGLETON = e
    monkeypatch.setenv(
        "SHOPAI_SHOPIFY_URL", "deguar.myshopify.com",
    )
    yield e
    _reset_ec()


def _checkout(**over):
    base = {
        "id": 99,
        "email": "jane@example.com",
        "customer": {
            "email": "jane@example.com",
            "first_name": "Jane",
        },
        "line_items": [
            {"title": "Galaxy Projector", "quantity": 1},
        ],
        "abandoned_checkout_url": (
            "https://deguar.myshopify.com/cart/r/abc"
        ),
    }
    base.update(over)
    return base


# ── Helpers ──────────────────────────────────────────────


class TestExtractors:
    def test_email_from_top_level(self):
        assert _extract_email({"email": "A@B.COM"}) == "a@b.com"

    def test_email_from_customer(self):
        assert _extract_email({
            "customer": {"email": "x@y.z"},
        }) == "x@y.z"

    def test_email_missing(self):
        assert _extract_email({}) == ""

    def test_first_name_from_customer(self):
        assert _extract_first_name(
            {"customer": {"first_name": "Mai"}},
            "a@b.c",
        ) == "Mai"

    def test_first_name_from_shipping(self):
        assert _extract_first_name(
            {"shipping_address": {"first_name": "Temu"}},
            "a@b.c",
        ) == "Temu"

    def test_first_name_from_email_local(self):
        """No first_name anywhere → derive from email."""
        assert _extract_first_name(
            {}, "jane.doe@example.com",
        ) == "Jane Doe"

    def test_first_name_fallback_there(self):
        assert _extract_first_name({}, "") == "there"

    def test_item_name_from_first_line(self):
        assert _extract_item_name({
            "line_items": [{"title": "Galaxy"}, {"title": "Moon"}],
        }) == "Galaxy"

    def test_item_name_empty_items(self):
        assert _extract_item_name({"line_items": []}) == ""

    def test_cart_url_from_abandoned(self):
        assert _build_cart_url(
            {"abandoned_checkout_url": "https://x/cart"},
            "",
        ) == "https://x/cart"

    def test_cart_url_fallback_to_host(self):
        """No abandoned URL → construct one from
        SHOPAI_SHOPIFY_URL."""
        assert _build_cart_url(
            {}, "deguar.myshopify.com",
        ).endswith("/cart")

    def test_cart_url_https_prepended(self):
        assert _build_cart_url(
            {}, "deguar.myshopify.com",
        ).startswith("https://")

    def test_is_completed_by_order_id(self):
        assert _is_completed({"order_id": 42})

    def test_is_completed_by_completed_at(self):
        assert _is_completed({
            "completed_at": "2026-04-22T10:30:00Z",
        })

    def test_is_completed_by_status(self):
        assert _is_completed({"status": "completed"})

    def test_not_completed(self):
        assert not _is_completed({})


# ── handle_checkout_update ───────────────────────────────


class TestHandler:
    def test_happy_path_enrols(self, email_engine):
        result = handle_checkout_update(_checkout())
        assert result["enrolled"] is True
        rows = email_engine.list_for_recipient(
            "jane@example.com",
        )
        assert len(rows) == 2  # 1h + 1d steps
        step_ids = {r.step_id for r in rows}
        assert step_ids == {
            "abandoned_reminder", "abandoned_discount",
        }

    def test_context_populated(self, email_engine):
        handle_checkout_update(_checkout())
        rows = email_engine.list_for_recipient(
            "jane@example.com",
        )
        ctx = rows[0].context
        assert ctx["first_name"] == "Jane"
        assert ctx["item_name"] == "Galaxy Projector"
        assert "deguar.myshopify.com" in ctx["cart_url"]
        # discount_code defaults when env unset
        assert ctx["discount_code"] == "SAVE10"

    def test_empty_cart_skipped(self, email_engine):
        result = handle_checkout_update(
            _checkout(line_items=[]),
        )
        assert result["enrolled"] is False
        assert "empty cart" in result["skipped_reason"]

    def test_no_email_skipped(self, email_engine):
        co = _checkout()
        co["email"] = ""
        co["customer"] = {}
        result = handle_checkout_update(co)
        assert result["enrolled"] is False
        assert "email" in result["skipped_reason"]

    def test_completed_checkout_skipped(self, email_engine):
        """Shopify sometimes fires checkouts/update AFTER the
        order has been created (async webhook fan-out). Don't
        enrol — the order webhook handles post-purchase."""
        result = handle_checkout_update(
            _checkout(order_id=12345),
        )
        assert result["enrolled"] is False
        assert "converted" in result["skipped_reason"]

    def test_idempotent_on_repeat_webhook(self, email_engine):
        """Shopify fires update on every mutation. Second
        webhook for the same checkout shouldn't duplicate
        enrollments — queue's idempotency key catches it."""
        handle_checkout_update(_checkout())
        handle_checkout_update(_checkout())
        rows = email_engine.list_for_recipient(
            "jane@example.com",
        )
        assert len(rows) == 2  # not 4

    def test_unsubscribed_returns_clean(self, email_engine):
        email_engine.unsubscribe(
            "jane@example.com", source="test",
        )
        result = handle_checkout_update(_checkout())
        assert result["enrolled"] is False
        assert "unsubscribe" in result["skipped_reason"].lower()


# ── order_handler cancels abandoned_cart ────────────────


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Full wire: email engine + budget_buyer engine + order
    handler all sharing tmp state."""
    _reset_bb()
    _reset_ec()

    tracker = LTVTracker(
        db_path=str(tmp_path / "ltv.db"),
        now_fn=lambda: 1_700_000_000.0,
    )
    bb = BudgetBuyerEngine(
        ltv_tracker=tracker,
        now_fn=lambda: 1_700_000_000.0,
    )
    import core.engines.budget_buyer.engine as bb_mod
    bb_mod._SINGLETON = bb

    eq = ScheduleQueue(
        db_path=str(tmp_path / "email.db"),
        now_fn=lambda: 1_700_000_000.0,
    )
    ec = EmailCampaignEngine(
        queue=eq, from_email="hello@deguar.com",
        now_fn=lambda: 1_700_000_000.0,
    )
    import core.engines.email_campaigns.engine as ec_mod
    ec_mod._SINGLETON = ec

    monkeypatch.setenv(
        "SHOPAI_SHOPIFY_URL", "deguar.myshopify.com",
    )

    yield {
        "handler": OrderWebhookHandler(),
        "email_engine": ec, "email_queue": eq,
        "ltv": tracker,
    }
    _reset_bb()
    _reset_ec()


class TestCancelOnOrder:
    def test_abandoned_cancelled_after_order(self, wired):
        """Full journey: abandoned cart enrols → buyer
        converts → order webhook cancels pending reminders."""
        # 1. Abandoned cart webhook
        handle_checkout_update(_checkout())
        rows_before = wired["email_engine"].list_for_recipient(
            "jane@example.com",
        )
        pending_before = [
            r for r in rows_before if r.status == "pending"
        ]
        assert len(pending_before) == 2

        # 2. Order arrives
        order = {
            "id": 555, "total_price": "29.99",
            "email": "jane@example.com",
            "customer": {
                "id": "c1", "email": "jane@example.com",
                "first_name": "Jane",
            },
            "line_items": [{"title": "Galaxy", "quantity": 1}],
            "note_attributes": [],
            "processed_at": "2026-04-22T10:30:00Z",
        }
        recorded = wired["handler"].handle_order_paid(order)

        # 3. Pending abandoned_cart rows cancelled
        assert recorded.get("abandoned_cart_cancelled") is True
        rows_after = wired["email_engine"].list_for_recipient(
            "jane@example.com",
        )
        abandoned_rows = [
            r for r in rows_after
            if r.flow_id == "abandoned_cart"
        ]
        for r in abandoned_rows:
            assert r.status == "cancelled"

    def test_no_abandoned_rows_still_ok(self, wired):
        """Buyer never abandoned — cancel call is a no-op +
        doesn't break the order webhook."""
        order = {
            "id": 555, "total_price": "29.99",
            "email": "fresh@example.com",
            "customer": {
                "id": "c2", "email": "fresh@example.com",
            },
            "line_items": [{"title": "x", "quantity": 1}],
            "note_attributes": [],
            "processed_at": "2026-04-22T10:30:00Z",
        }
        recorded = wired["handler"].handle_order_paid(order)
        assert recorded.get("abandoned_cart_cancelled") is True

    def test_sent_row_not_cancelled(self, wired):
        """If the 1h reminder already sent, leave it alone —
        only pending rows get cancelled."""
        handle_checkout_update(_checkout())
        # Simulate the 1h reminder firing
        for r in wired["email_queue"].list_by_recipient(
            "jane@example.com",
        ):
            if r.step_id == "abandoned_reminder":
                wired["email_queue"].mark_sent(
                    r.row_id, message_id="mock",
                )

        order = {
            "id": 555, "total_price": "29.99",
            "email": "jane@example.com",
            "customer": {
                "id": "c1", "email": "jane@example.com",
            },
            "line_items": [{"title": "x", "quantity": 1}],
            "note_attributes": [],
            "processed_at": "2026-04-22T10:30:00Z",
        }
        wired["handler"].handle_order_paid(order)
        # Reminder still sent; discount cancelled
        rows = wired["email_queue"].list_by_recipient(
            "jane@example.com",
        )
        by_step = {r.step_id: r.status for r in rows}
        assert by_step["abandoned_reminder"] == "sent"
        assert by_step["abandoned_discount"] == "cancelled"

    def test_cancel_failure_does_not_break_webhook(self, wired):
        with patch.object(
            wired["email_engine"], "cancel_flow",
            side_effect=RuntimeError("db locked"),
        ):
            recorded = wired["handler"].handle_order_paid({
                "id": 1, "total_price": "10",
                "email": "jane@example.com",
                "customer": {"id": "c1"},
                "line_items": [],
                "note_attributes": [],
                "processed_at": "2026-04-22T10:30:00Z",
            })
        # Webhook completed
        assert "order_id" in recorded
        assert recorded.get("abandoned_cart_cancelled") is False
