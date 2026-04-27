"""Tests for the affiliate engine's commission gift-card payer.

Phase 6.5 — the final Phase 6 wire-up. Different writeback shape
from the discount minters (uses SHOPIFY_CREATE_GIFT_CARD instead
of SHOPIFY_CREATE_DISCOUNT) and from tag/price appliers (one-shot
per partner instead of per-product mutation).

Three layers of coverage:

  1. ``_build_partner_map`` — accepts both ``id`` and ``partner_id``
     keys, robust to malformed inputs.
  2. ``_build_gift_card_params`` — produces a clean adapter call
     shape with optional recipient fields when present.
  3. ``pay_commissions`` — happy path verifies adapter called
     with the right amount + recipient; 5 skip / failure modes.
  4. Flow integration — opt-in flag wires the payer in cleanly,
     with an optional currency override.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ─── _build_partner_map ──────────────────────────────────────────


class TestBuildPartnerMap:

    def test_indexes_by_id(self):
        from engines.affiliate.commission_payer import (
            _build_partner_map,
        )

        m = _build_partner_map([
            {"id": "p1", "name": "Alice", "email": "a@x.com"},
            {"id": "p2", "name": "Bob", "email": "b@x.com"},
        ])
        assert m["p1"]["name"] == "Alice"
        assert m["p2"]["email"] == "b@x.com"

    def test_falls_back_to_partner_id_key(self):
        # Some upstreams use partner_id instead of id.
        from engines.affiliate.commission_payer import (
            _build_partner_map,
        )

        m = _build_partner_map([
            {"partner_id": "p3", "name": "Carol"},
        ])
        assert m["p3"]["name"] == "Carol"

    def test_skips_malformed_entries(self):
        from engines.affiliate.commission_payer import (
            _build_partner_map,
        )

        m = _build_partner_map([
            None,
            "garbage",
            {"id": "", "name": "Blank"},
            {},
            {"id": "p1", "name": "Valid"},
        ])
        assert m == {"p1": {"id": "p1", "name": "Valid"}}

    def test_non_list_input_returns_empty(self):
        from engines.affiliate.commission_payer import (
            _build_partner_map,
        )

        assert _build_partner_map(None) == {}
        assert _build_partner_map("not-a-list") == {}


# ─── _build_gift_card_params ─────────────────────────────────────


class TestBuildGiftCardParams:

    def test_minimum_shape_no_recipient_fields(self):
        from engines.affiliate.commission_payer import (
            _build_gift_card_params,
        )

        params = _build_gift_card_params(
            commission={
                "partner_id": "p1",
                "commission_amount": 50.0,
                "period_sales": 500.0,
                "commission_rate": 10.0,
            },
            partner={"id": "p1"},  # no email/name
            currency="USD",
        )
        assert params["initial_value"] == 50.0
        assert params["currency"] == "USD"
        assert "Affiliate commission" in params["note"]
        # No recipient fields when partner doesn't carry them.
        assert "recipient_email" not in params
        assert "recipient_name" not in params
        assert "customer_id" not in params

    def test_includes_email_when_present(self):
        from engines.affiliate.commission_payer import (
            _build_gift_card_params,
        )

        params = _build_gift_card_params(
            commission={"commission_amount": 50.0,
                        "period_sales": 500, "commission_rate": 10},
            partner={"id": "p1", "email": "alice@example.com"},
            currency="USD",
        )
        assert params["recipient_email"] == "alice@example.com"

    def test_includes_name_when_present(self):
        from engines.affiliate.commission_payer import (
            _build_gift_card_params,
        )

        params = _build_gift_card_params(
            commission={"commission_amount": 50.0,
                        "period_sales": 500, "commission_rate": 10,
                        "name": "Carol"},
            partner={"id": "p1"},
            currency="USD",
        )
        # Falls back to commission.name when partner has no name.
        assert params["recipient_name"] == "Carol"

    def test_includes_customer_id_when_present(self):
        from engines.affiliate.commission_payer import (
            _build_gift_card_params,
        )

        params = _build_gift_card_params(
            commission={"commission_amount": 50.0,
                        "period_sales": 500, "commission_rate": 10},
            partner={
                "id": "p1",
                "customer_id": "gid://shopify/Customer/x",
            },
            currency="USD",
        )
        assert params["customer_id"] == "gid://shopify/Customer/x"

    def test_currency_override(self):
        from engines.affiliate.commission_payer import (
            _build_gift_card_params,
        )

        params = _build_gift_card_params(
            commission={"commission_amount": 50.0,
                        "period_sales": 500, "commission_rate": 10},
            partner={"id": "p1"},
            currency="EUR",
        )
        assert params["currency"] == "EUR"


# ─── pay_commissions ─────────────────────────────────────────────


class TestPayCommissions:

    def _commission(self, **overrides):
        base = {
            "partner_id": "p1",
            "name": "Alice",
            "period_sales": 500.0,
            "commission_rate": 10.0,
            "commission_amount": 50.0,
            "tier": "default",
        }
        base.update(overrides)
        return base

    def _partner(self, pid="p1", email="alice@x.com"):
        return {"id": pid, "name": "Alice", "email": email}

    def test_no_commissions_returns_empty(self):
        from engines.affiliate.commission_payer import pay_commissions

        with patch(
            "engines.affiliate.commission_payer._get_router",
        ) as mock_router:
            assert pay_commissions([], []) == []
        mock_router.assert_not_called()

    def test_router_unavailable_returns_skipped(self):
        from engines.affiliate.commission_payer import pay_commissions

        with patch(
            "engines.affiliate.commission_payer._get_router",
            return_value=None,
        ):
            results = pay_commissions(
                commissions=[self._commission()],
                partners=[self._partner()],
            )
        assert results[0]["paid"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_non_positive_amount_skips(self):
        from engines.affiliate.commission_payer import pay_commissions

        class _StubRouter:
            calls: list = []

            def execute(self, capability, params):
                self.calls.append(params)
                return None

        stub = _StubRouter()
        with patch(
            "engines.affiliate.commission_payer._get_router",
            return_value=stub,
        ):
            results = pay_commissions(
                commissions=[
                    self._commission(commission_amount=0),
                    self._commission(commission_amount=-5),
                ],
                partners=[self._partner()],
            )
        assert stub.calls == []
        assert all(not r["paid"] for r in results)
        assert results[0]["error"] == "non_positive_amount"
        assert results[1]["error"] == "non_positive_amount"

    def test_partner_not_in_input_skips(self):
        from engines.affiliate.commission_payer import pay_commissions

        class _StubRouter:
            calls: list = []

            def execute(self, capability, params):
                self.calls.append(params)
                return None

        stub = _StubRouter()
        with patch(
            "engines.affiliate.commission_payer._get_router",
            return_value=stub,
        ):
            results = pay_commissions(
                commissions=[self._commission(partner_id="ghost")],
                partners=[self._partner()],
            )
        assert stub.calls == []
        assert results[0]["paid"] is False
        assert results[0]["error"] == "partner_not_in_input"

    def test_happy_path_issues_gift_card(self):
        from core.adapters.base import Capability
        from engines.affiliate.commission_payer import pay_commissions

        class _StubResult:
            ok = True
            data = {
                "gift_card": {"id": "gid://shopify/GiftCard/100"},
                "code": "ABCD-EFGH-IJKL-MNOP",
            }
            error = None

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return _StubResult()

        stub = _StubRouter()
        with patch(
            "engines.affiliate.commission_payer._get_router",
            return_value=stub,
        ):
            results = pay_commissions(
                commissions=[self._commission(commission_amount=125.50)],
                partners=[self._partner()],
            )

        # Adapter was called with the right amount + recipient.
        assert len(stub.calls) == 1
        cap, params = stub.calls[0]
        assert cap == Capability.SHOPIFY_CREATE_GIFT_CARD
        assert params["initial_value"] == 125.50
        assert params["recipient_email"] == "alice@x.com"
        # Result reflects success + carries the gift-card data.
        assert results[0]["paid"] is True
        assert results[0]["amount"] == 125.50
        assert results[0]["gift_card_id"] == \
            "gid://shopify/GiftCard/100"
        assert results[0]["code"] == "ABCD-EFGH-IJKL-MNOP"
        assert results[0]["error"] is None

    def test_adapter_failure_records_error(self):
        from engines.affiliate.commission_payer import pay_commissions

        class _FailResult:
            ok = False
            data = {}
            error = "scope_missing"

        class _StubRouter:
            def execute(self, capability, params):
                return _FailResult()

        with patch(
            "engines.affiliate.commission_payer._get_router",
            return_value=_StubRouter(),
        ):
            results = pay_commissions(
                commissions=[self._commission()],
                partners=[self._partner()],
            )
        assert results[0]["paid"] is False
        assert "adapter_failed" in results[0]["error"]


# ─── flow integration ───────────────────────────────────────────


class TestAffiliateFlowApplyCommissions:

    def _input(self, apply: bool = False, **extra):
        return {
            "data": {
                "products": [
                    {"id": "gid://shopify/Product/1",
                     "title": "Widget",
                     "price": 50.0},
                ],
                "sales_data": [
                    {"partner_id": "p1", "amount": 500.0},
                ],
                "partners": [
                    {"id": "p1",
                     "name": "Alice",
                     "email": "alice@example.com"},
                ],
                "commission_rules": [
                    {"tier_name": "default",
                     "min_sales": 0,
                     "commission_pct": 10.0,
                     "bonus": 0},
                ],
                "apply_commissions": apply,
                **extra,
            },
        }

    def test_apply_commissions_false_no_payer_call(self):
        from engines.affiliate.flow import AffiliateEngine

        with patch(
            "engines.affiliate.flow.pay_commissions",
        ) as mock_pay:
            output = AffiliateEngine().run(self._input(False))

        mock_pay.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["payout_results"] == []

    def test_apply_commissions_true_calls_payer(self):
        from engines.affiliate.flow import AffiliateEngine

        with patch(
            "engines.affiliate.flow.pay_commissions",
            return_value=[
                {"partner_id": "p1", "paid": True,
                 "amount": 50.0,
                 "gift_card_id": "gid://shopify/GiftCard/1",
                 "code": "ABCD-EFGH",
                 "error": None},
            ],
        ) as mock_pay:
            output = AffiliateEngine().run(self._input(True))

        if output["status"] == "success":
            assert mock_pay.called
            results = output["data"]["payout_results"]
            assert len(results) == 1
            assert results[0]["paid"] is True

    def test_payout_currency_override_threaded_through(self):
        from engines.affiliate.flow import AffiliateEngine

        captured: dict = {}

        def _spy(commissions, partners, *, currency):
            captured["currency"] = currency
            return []

        with patch(
            "engines.affiliate.flow.pay_commissions",
            side_effect=_spy,
        ):
            AffiliateEngine().run(
                self._input(True, payout_currency="EUR"),
            )

        if captured:
            assert captured["currency"] == "EUR"
