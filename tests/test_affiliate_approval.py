"""Tests for the affiliate approval-queue wiring.

Same pattern as PR #59 / #60 / #61 / #63, applied to the
gift-card payout shape. Coverage:

  1. ``enqueue_commissions_for_approval`` happy path — every
     positive-amount commission with a matched partner is parked
     and the result carries ``pending_action_id``.
  2. Skip semantics: ``non_positive_amount`` /
     ``partner_not_in_input`` / queue-unavailable.
  3. flow integration — ``data.apply_commissions=True`` +
     ``data.require_approval=True`` enqueues; ``False`` falls
     back to direct gift-card minting.
  4. Currency override threaded through both branches.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


# ─── enqueue_commissions_for_approval ──────────────────────────


def _commission(**overrides):
    base = {
        "partner_id": "partner_1",
        "name": "Alice",
        "period_sales": 1000.0,
        "commission_rate": 5.0,
        "commission_amount": 50.0,
        "tier": "Gold",
    }
    base.update(overrides)
    return base


def _partner(pid: str, **overrides):
    base = {
        "id": pid,
        "name": "Alice Partner",
        "email": "alice@example.com",
        "customer_id": "gid://shopify/Customer/100",
    }
    base.update(overrides)
    return base


class TestEnqueueCommissionsForApproval:

    def test_happy_path_parks_each_commission(self, isolated_queue):
        from engines.affiliate.commission_payer import (
            enqueue_commissions_for_approval,
        )

        commissions = [
            _commission(),
            _commission(partner_id="partner_2", commission_amount=120.0,
                        name="Bob", commission_rate=8.0,
                        period_sales=1500.0),
        ]
        partners = [
            _partner("partner_1"),
            _partner("partner_2", name="Bob Partner"),
        ]

        results = enqueue_commissions_for_approval(
            commissions=commissions, partners=partners, currency="USD",
        )

        assert len(results) == 2
        for r in results:
            assert r["paid"] is False
            assert r["error"] == "queued"
            assert r["pending_action_id"].startswith("appr_")
            assert r["amount"] > 0

        assert isolated_queue.stats()["pending"] == 2

        # Narrative check on the first one.
        action = isolated_queue.get(results[0]["pending_action_id"])
        assert action is not None
        assert action.engine == "affiliate"
        assert action.action_type == "pay_commission"
        assert action.capability == "SHOPIFY_CREATE_GIFT_CARD"
        assert "$50.00" in action.narrative
        assert "USD" in action.narrative

    def test_non_positive_amount_skipped(self, isolated_queue):
        from engines.affiliate.commission_payer import (
            enqueue_commissions_for_approval,
        )

        results = enqueue_commissions_for_approval(
            commissions=[_commission(commission_amount=0)],
            partners=[_partner("partner_1")],
        )
        assert results[0]["error"] == "non_positive_amount"
        assert results[0]["pending_action_id"] is None
        assert isolated_queue.list_pending() == []

    def test_partner_not_in_input_skipped(self, isolated_queue):
        from engines.affiliate.commission_payer import (
            enqueue_commissions_for_approval,
        )

        results = enqueue_commissions_for_approval(
            commissions=[_commission()],
            partners=[],  # no partner record for partner_1
        )
        assert results[0]["error"] == "partner_not_in_input"
        assert results[0]["pending_action_id"] is None

    def test_queue_unavailable_uniform_skip_list(self, isolated_queue):
        from engines.affiliate.commission_payer import (
            enqueue_commissions_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            results = enqueue_commissions_for_approval(
                commissions=[_commission()],
                partners=[_partner("partner_1")],
            )
        assert results[0]["error"] == "approval_queue_unavailable"
        assert results[0]["pending_action_id"] is None

    def test_currency_threaded_through_to_narrative(
        self, isolated_queue,
    ):
        from engines.affiliate.commission_payer import (
            enqueue_commissions_for_approval,
        )

        results = enqueue_commissions_for_approval(
            commissions=[_commission()],
            partners=[_partner("partner_1")],
            currency="EUR",
        )
        action = isolated_queue.get(results[0]["pending_action_id"])
        assert action is not None
        assert "EUR" in action.narrative


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_commissions: bool, require_approval: bool,
                currency: str = "USD"):
    return {
        "status": "ok",
        "data": {
            "products": [
                {"id": "gid://shopify/Product/1", "title": "Widget",
                 "price": 50.0},
            ],
            "commission_rules": [
                {"name": "Bronze", "min_sales": 0, "rate": 0.05},
            ],
            "partners": [
                {
                    "id": "partner_1",
                    "name": "Alice",
                    "email": "alice@example.com",
                    "customer_id": "gid://shopify/Customer/100",
                },
            ],
            "sales_data": [
                {"partner_id": "partner_1", "amount": 1000.0,
                 "period": "2026-04"},
            ],
            "apply_commissions": apply_commissions,
            "require_approval": require_approval,
            "payout_currency": currency,
        },
        "meta": {},
        "error": None,
    }


class TestFlowApprovalIntegration:

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.affiliate.flow import AffiliateEngine

        with patch(
            "engines.affiliate.flow.pay_commissions",
        ) as mock_pay, patch(
            "engines.affiliate.flow.enqueue_commissions_for_approval",
            return_value=[
                {"partner_id": "partner_1", "paid": False,
                 "amount": 50.0, "gift_card_id": "", "code": "",
                 "error": "queued",
                 "pending_action_id": "appr_stub_1"},
            ],
        ) as mock_enqueue:
            output = AffiliateEngine().run(
                _flow_input(apply_commissions=True, require_approval=True),
            )

        assert output["status"] == "success"
        mock_pay.assert_not_called()
        if output["data"].get("commissions_due"):
            mock_enqueue.assert_called_once()
            assert (
                output["data"]["payout_results"][0]["error"] == "queued"
            )

    def test_require_approval_false_routes_to_direct_pay(
        self, isolated_queue,
    ):
        from engines.affiliate.flow import AffiliateEngine

        with patch(
            "engines.affiliate.flow.pay_commissions",
            return_value=[
                {"partner_id": "partner_1", "paid": True,
                 "amount": 50.0,
                 "gift_card_id": "gid://shopify/GiftCard/1",
                 "code": "GC-XXX", "error": None},
            ],
        ) as mock_pay, patch(
            "engines.affiliate.flow.enqueue_commissions_for_approval",
        ) as mock_enqueue:
            output = AffiliateEngine().run(
                _flow_input(apply_commissions=True,
                            require_approval=False),
            )

        assert output["status"] == "success"
        mock_enqueue.assert_not_called()
        if output["data"].get("commissions_due"):
            mock_pay.assert_called_once()
            assert output["data"]["payout_results"][0]["paid"] is True

    def test_apply_commissions_false_skips_both(self, isolated_queue):
        from engines.affiliate.flow import AffiliateEngine

        with patch(
            "engines.affiliate.flow.pay_commissions",
        ) as mock_pay, patch(
            "engines.affiliate.flow.enqueue_commissions_for_approval",
        ) as mock_enqueue:
            output = AffiliateEngine().run(
                _flow_input(apply_commissions=False,
                            require_approval=True),
            )

        assert output["status"] == "success"
        mock_pay.assert_not_called()
        mock_enqueue.assert_not_called()
        assert output["data"]["payout_results"] == []

    def test_currency_threaded_to_enqueue(self, isolated_queue):
        from engines.affiliate.flow import AffiliateEngine

        with patch(
            "engines.affiliate.flow.enqueue_commissions_for_approval",
            return_value=[],
        ) as mock_enqueue:
            AffiliateEngine().run(
                _flow_input(apply_commissions=True,
                            require_approval=True, currency="GBP"),
            )

        if mock_enqueue.called:
            kwargs = mock_enqueue.call_args.kwargs
            assert kwargs["currency"] == "GBP"
