"""TikTokShopPoller regression + cycle wire-up."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from engines.tiktok_shop_poller import (
    PollerSummary,
    TikTokShopPoller,
)


@pytest.fixture
def poller():
    tmp = tempfile.NamedTemporaryFile(
        suffix=".db", delete=False,
    )
    tmp.close()
    p = TikTokShopPoller.open(tmp.name)
    yield p
    p.close()
    os.unlink(tmp.name)


def _adapter(available=True, orders=None):
    m = MagicMock()
    m.is_available.return_value = available
    m.fetch_orders.return_value = orders or []
    return m


# ── Guards ────────────────────────────────────────────────


class TestGuards:
    def test_unconfigured_returns_silent_summary(self, poller):
        out = poller.poll_once(adapter=_adapter(available=False))
        assert isinstance(out, PollerSummary)
        assert out.new == 0
        assert out.reason == "not_configured"

    def test_adapter_fetch_raises_is_soft(self, poller):
        adapter = MagicMock()
        adapter.is_available.return_value = True
        adapter.fetch_orders.side_effect = RuntimeError("x")
        out = poller.poll_once(adapter=adapter)
        assert out.new == 0
        assert "fetch_error" in out.reason

    def test_non_list_return_is_soft(self, poller):
        adapter = MagicMock()
        adapter.is_available.return_value = True
        adapter.fetch_orders.return_value = "oops"
        out = poller.poll_once(adapter=adapter)
        assert out.new == 0
        assert out.reason == "fetch_returned_non_list"


# ── Happy path + idempotency ─────────────────────────────


class TestPollHappy:
    def test_new_orders_emitted_once(self, poller):
        orders = [
            {
                "order_id": "T-1",
                "total_amount": 25.50,
                "currency": "USD",
                "line_items": [{"sku_id": "S1"}],
                "buyer_email": "b@x.com",
            },
            {
                "order_id": "T-2",
                "total_amount": 10.0,
                "currency": "USD",
                "line_items": [],
            },
            "malformed",
        ]
        bus = MagicMock()
        out = poller.poll_once(
            adapter=_adapter(orders=orders),
            bus=bus,
        )
        assert out.polled == 3
        assert out.new == 2
        assert out.emitted == 2
        assert out.emit_errors == 0
        assert bus.report.call_count == 2

    def test_second_poll_skips_already_seen(self, poller):
        orders = [{
            "order_id": "T-1", "total_amount": 25.0,
            "currency": "USD", "line_items": [],
        }]
        bus = MagicMock()
        poller.poll_once(
            adapter=_adapter(orders=orders), bus=bus,
        )
        # Same orders again — zero new emits.
        out = poller.poll_once(
            adapter=_adapter(orders=orders), bus=bus,
        )
        assert out.new == 0
        assert out.emitted == 0

    def test_emitted_outcome_shape(self, poller):
        from core.integration.engine_outcome_bus import (
            EngineOutcome,
        )
        orders = [{
            "order_id": "T-9",
            "total_amount": 19.99,
            "currency": "eur",
            "line_items": [
                {"sku_id": "S1"}, {"sku_id": "S2"},
            ],
            "buyer_email": "Bata@example.com",
        }]
        bus = MagicMock()
        poller.poll_once(
            adapter=_adapter(orders=orders), bus=bus,
        )
        outcome = bus.report.call_args.args[0]
        assert isinstance(outcome, EngineOutcome)
        assert outcome.engine == "tiktok_shop"
        assert outcome.kpi == "revenue_usd"
        assert outcome.value == 19.99
        assert outcome.ok is True
        assert outcome.source == "tiktok_shop_poller"
        ctx = outcome.context
        assert ctx["order_id"] == "T-9"
        # Currency preserved from source.
        assert ctx["currency"] == "eur"
        assert ctx["line_item_count"] == 2
        # PII hashed, not raw.
        assert ctx["buyer_email_hash"]
        assert "@" not in ctx["buyer_email_hash"]

    def test_emit_exception_counts_but_does_not_break(
        self, poller,
    ):
        bus = MagicMock()
        bus.report.side_effect = RuntimeError("sink down")
        orders = [{
            "order_id": "T-1", "total_amount": 5.0,
            "currency": "USD", "line_items": [],
        }]
        out = poller.poll_once(
            adapter=_adapter(orders=orders), bus=bus,
        )
        # Still marked seen + counted as new, but emit failed.
        assert out.new == 1
        assert out.emitted == 0
        assert out.emit_errors == 1

    def test_zero_total_marks_not_ok(self, poller):
        orders = [{
            "order_id": "T-0", "total_amount": 0,
            "currency": "USD", "line_items": [],
        }]
        bus = MagicMock()
        poller.poll_once(
            adapter=_adapter(orders=orders), bus=bus,
        )
        outcome = bus.report.call_args.args[0]
        assert outcome.ok is False


# ── Persistence across open/close ─────────────────────────


class TestPersistence:
    def test_seen_cache_survives_reopen(self, tmp_path):
        db = str(tmp_path / "tts.db")
        bus = MagicMock()
        orders = [{
            "order_id": "T-99", "total_amount": 5.0,
            "currency": "USD", "line_items": [],
        }]
        p1 = TikTokShopPoller.open(db)
        p1.poll_once(
            adapter=_adapter(orders=orders), bus=bus,
        )
        p1.close()
        # New instance, same DB.
        p2 = TikTokShopPoller.open(db)
        out = p2.poll_once(
            adapter=_adapter(orders=orders), bus=bus,
        )
        assert out.new == 0
        p2.close()


# ── Controller wire check ─────────────────────────────────


class TestControllerWire:
    def test_phase_5a3_referenced(self):
        import inspect
        from core.autonomous import controller as ctl
        src = inspect.getsource(ctl)
        assert "# Phase 5a3: TIKTOK SHOP POLLER" in src
        assert "engines.tiktok_shop_poller" in src
        assert "poll_once" in src
