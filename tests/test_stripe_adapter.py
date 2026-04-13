"""Tests for the Stripe payment adapter.

Mirrors the PayPal test suite structure. Real HTTP calls are
forbidden — every test patches ``_stripe_form_post`` / ``_http_get``
so the suite stays hermetic.

Coverage matrix:

  * StripeAdapter metadata (name, category, capabilities, priority)
  * is_configured() requires STRIPE_SECRET_KEY
  * is_live() detects sk_live_ vs sk_test_ prefix
  * Refund happy path (full + partial + PaymentIntent id)
  * Capture happy path (full + partial)
  * List disputes happy path
  * Amount conversion (USD cents, JPY zero-decimal)
  * HTTP error mapping (auth, rate limit)
  * Bootstrap registers stripe alongside paypal
  * SmartRouter routes to stripe when configured
  * SmartRouter prefers paypal (priority 80) over stripe (70)
  * End-to-end router.execute + metrics capture
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterAuthError,
    AdapterCategory,
    AdapterRateLimited,
    AdapterValidationError,
    Capability,
    NoAdapterAvailable,
    get_config,
    get_metrics,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Clear all payment env vars + singletons between tests."""
    for var in (
        "STRIPE_SECRET_KEY",
        "STRIPE_API_VERSION",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_ENV",
        "BREVO_API_KEY",
        "RESEND_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_stripe(monkeypatch, *, key="sk_test_abc123"):
    monkeypatch.setenv("STRIPE_SECRET_KEY", key)
    get_config().reload()


def _configure_paypal(monkeypatch, *, env="sandbox"):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "AYxxxxxxxx")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "ELxxxxxxxx")
    monkeypatch.setenv("PAYPAL_ENV", env)
    get_config().reload()


_VALID_REFUND = {
    "transaction_id": "ch_1A2B3C4D5E6F7G8H",
    "amount": "12.34",
    "currency": "USD",
    "reason": "requested_by_customer",
}

_VALID_REFUND_PI = {
    "transaction_id": "pi_1A2B3C4D5E6F7G8H",
    "amount": "25.00",
    "currency": "USD",
}

_VALID_CAPTURE = {
    "authorization_id": "ch_UNCAPTURED123",
    "amount": "49.99",
    "currency": "USD",
}


# ── StripeAdapter metadata ─────────────────────────────────


class TestStripeMetadata:
    def test_metadata(self):
        from core.adapters.payment.stripe import StripeAdapter
        a = StripeAdapter()
        assert a.name == "stripe"
        assert a.category == AdapterCategory.PAYMENT
        assert Capability.PAYMENT_REFUND in a.capabilities
        assert Capability.PAYMENT_CAPTURE in a.capabilities
        assert Capability.PAYMENT_LIST_DISPUTES in a.capabilities
        assert a.priority == 70
        assert a.cost_per_call == 0.0


# ── Configuration ──────────────────────────────────────────


class TestStripeConfiguration:
    def test_unconfigured_without_key(self):
        from core.adapters.payment.stripe import StripeAdapter
        assert not StripeAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        assert StripeAdapter().is_configured()

    def test_is_live_false_for_test_key(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch, key="sk_test_abc123")
        assert not StripeAdapter().is_live()

    def test_is_live_true_for_live_key(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch, key="sk_live_abc123")
        assert StripeAdapter().is_live()

    def test_bearer_token_returns_secret_key(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch, key="sk_test_xyz")
        a = StripeAdapter()
        assert a._bearer_token() == "sk_test_xyz"

    def test_auth_headers_include_stripe_version(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()
        headers = a._auth_headers()
        assert "Stripe-Version" in headers
        assert headers["Authorization"].startswith("Bearer sk_test_")


# ── Amount conversion ──────────────────────────────────────


class TestAmountConversion:
    def test_usd_to_cents(self):
        from core.adapters.payment.stripe import _amount_to_cents
        assert _amount_to_cents("12.34", "USD") == 1234

    def test_usd_whole_dollars(self):
        from core.adapters.payment.stripe import _amount_to_cents
        assert _amount_to_cents("100.00", "USD") == 10000

    def test_jpy_zero_decimal(self):
        from core.adapters.payment.stripe import _amount_to_cents
        assert _amount_to_cents("500", "JPY") == 500

    def test_eur_to_cents(self):
        from core.adapters.payment.stripe import _amount_to_cents
        assert _amount_to_cents("9.99", "EUR") == 999

    def test_rounding(self):
        from core.adapters.payment.stripe import _amount_to_cents
        # 19.995 should round to 2000 cents
        assert _amount_to_cents("19.995", "USD") == 2000


# ── Refund happy path ─────────────────────────────────────


class TestStripeRefund:
    def test_partial_refund_with_charge_id(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_post(url, data):
            captured["url"] = url
            captured["data"] = data
            return {
                "id": "re_1ABC",
                "status": "succeeded",
                "amount": 1234,
                "currency": "usd",
            }

        with patch.object(a, "_stripe_form_post", side_effect=fake_post):
            result = a.execute(Capability.PAYMENT_REFUND, dict(_VALID_REFUND))

        assert result.ok
        assert result.data["refund_id"] == "re_1ABC"
        assert result.data["status"] == "SUCCEEDED"
        assert result.data["amount"] == "12.34"
        assert result.data["currency"] == "USD"
        assert result.data["transaction_id"] == "ch_1A2B3C4D5E6F7G8H"

        assert "/v1/refunds" in captured["url"]
        assert captured["data"]["charge"] == "ch_1A2B3C4D5E6F7G8H"
        assert captured["data"]["amount"] == 1234

    def test_refund_with_payment_intent_id(self, monkeypatch):
        """pi_ prefix → payload uses payment_intent instead of charge."""
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_post(url, data):
            captured["data"] = data
            return {
                "id": "re_2DEF",
                "status": "succeeded",
                "amount": 2500,
                "currency": "usd",
            }

        with patch.object(a, "_stripe_form_post", side_effect=fake_post):
            result = a.execute(Capability.PAYMENT_REFUND, dict(_VALID_REFUND_PI))

        assert result.ok
        assert captured["data"]["payment_intent"] == "pi_1A2B3C4D5E6F7G8H"
        assert "charge" not in captured["data"]

    def test_full_refund_omits_amount(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_post(url, data):
            captured["data"] = data
            return {
                "id": "re_FULL",
                "status": "succeeded",
                "amount": 5000,
                "currency": "usd",
            }

        params = {"transaction_id": "ch_FULL123"}

        with patch.object(a, "_stripe_form_post", side_effect=fake_post):
            result = a.execute(Capability.PAYMENT_REFUND, params)

        assert result.ok
        assert "amount" not in captured["data"]

    def test_refund_includes_reason(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_post(url, data):
            captured["data"] = data
            return {"id": "re_R", "status": "succeeded", "amount": 100, "currency": "usd"}

        with patch.object(a, "_stripe_form_post", side_effect=fake_post):
            a.execute(Capability.PAYMENT_REFUND, dict(_VALID_REFUND))

        assert captured["data"]["reason"] == "requested_by_customer"

    def test_refund_includes_metadata(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_post(url, data):
            captured["data"] = data
            return {"id": "re_M", "status": "succeeded", "amount": 100, "currency": "usd"}

        params = dict(_VALID_REFUND)
        params["metadata"] = {"order_id": "1001", "shop": "test"}

        with patch.object(a, "_stripe_form_post", side_effect=fake_post):
            a.execute(Capability.PAYMENT_REFUND, params)

        assert captured["data"]["metadata[order_id]"] == "1001"
        assert captured["data"]["metadata[shop]"] == "test"

    def test_refund_auth_error_mapped(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()
        with patch.object(
            a, "_stripe_form_post",
            side_effect=AdapterAuthError(a.name, "bad key"),
        ):
            result = a.execute(Capability.PAYMENT_REFUND, dict(_VALID_REFUND))
        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_refund_rate_limit_mapped(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()
        with patch.object(
            a, "_stripe_form_post",
            side_effect=AdapterRateLimited(a.name, "throttled"),
        ):
            result = a.execute(Capability.PAYMENT_REFUND, dict(_VALID_REFUND))
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)

    def test_refund_jpy_zero_decimal(self, monkeypatch):
        """JPY refund: amount stays as integer (no cents conversion)."""
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_post(url, data):
            captured["data"] = data
            return {"id": "re_JPY", "status": "succeeded", "amount": 500, "currency": "jpy"}

        params = {
            "transaction_id": "ch_JPY123",
            "amount": "500",
            "currency": "JPY",
        }

        with patch.object(a, "_stripe_form_post", side_effect=fake_post):
            result = a.execute(Capability.PAYMENT_REFUND, params)

        assert result.ok
        assert captured["data"]["amount"] == 500
        assert result.data["amount"] == "500"


# ── Capture happy path ─────────────────────────────────────


class TestStripeCapture:
    def test_partial_capture_happy_path(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_post(url, data):
            captured["url"] = url
            captured["data"] = data
            return {
                "id": "ch_UNCAPTURED123",
                "status": "succeeded",
                "amount_captured": 4999,
                "currency": "usd",
            }

        with patch.object(a, "_stripe_form_post", side_effect=fake_post):
            result = a.execute(Capability.PAYMENT_CAPTURE, dict(_VALID_CAPTURE))

        assert result.ok
        assert result.data["capture_id"] == "ch_UNCAPTURED123"
        assert result.data["status"] == "SUCCEEDED"
        assert result.data["amount"] == "49.99"
        assert result.data["authorization_id"] == "ch_UNCAPTURED123"
        assert "/v1/charges/ch_UNCAPTURED123/capture" in captured["url"]
        assert captured["data"]["amount"] == 4999

    def test_full_capture_omits_amount(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_post(url, data):
            captured["data"] = data
            return {
                "id": "ch_FULL",
                "status": "succeeded",
                "amount_captured": 10000,
                "currency": "usd",
            }

        params = {"authorization_id": "ch_FULL"}

        with patch.object(a, "_stripe_form_post", side_effect=fake_post):
            result = a.execute(Capability.PAYMENT_CAPTURE, params)

        assert result.ok
        assert "amount" not in captured["data"]


# ── List disputes ──────────────────────────────────────────


class TestStripeListDisputes:
    def test_list_disputes_happy_path(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {
                "data": [
                    {
                        "id": "dp_1ABC",
                        "status": "needs_response",
                        "reason": "fraudulent",
                        "amount": 1234,
                        "currency": "usd",
                    },
                    {
                        "id": "dp_2DEF",
                        "status": "won",
                        "reason": "product_not_received",
                        "amount": 5000,
                        "currency": "usd",
                    },
                ],
            }

        with patch.object(a, "_http_get", side_effect=fake_get):
            result = a.execute(
                Capability.PAYMENT_LIST_DISPUTES,
                {"page_size": 10, "status": "NEEDS_RESPONSE"},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["disputes"][0]["dispute_id"] == "dp_1ABC"
        assert result.data["disputes"][0]["amount"] == "12.34"
        assert result.data["disputes"][0]["status"] == "needs_response"
        assert "limit=10" in captured["url"]
        assert "status=needs_response" in captured["url"]

    def test_list_disputes_clamps_page_size(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {"data": []}

        with patch.object(a, "_http_get", side_effect=fake_get):
            a.execute(
                Capability.PAYMENT_LIST_DISPUTES,
                {"page_size": 999},
            )

        assert "limit=100" in captured["url"]

    def test_list_disputes_with_date_filter(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()

        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {"data": []}

        with patch.object(a, "_http_get", side_effect=fake_get):
            a.execute(
                Capability.PAYMENT_LIST_DISPUTES,
                {"created_after": "2024-01-01T00:00:00Z"},
            )

        assert "created[gte]=" in captured["url"]


# ── Validation (inherited from PaymentBaseAdapter) ─────────


class TestStripeValidation:
    def test_refund_requires_transaction_id(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()
        params = dict(_VALID_REFUND)
        del params["transaction_id"]
        result = a.execute(Capability.PAYMENT_REFUND, params)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_capture_requires_authorization_id(self, monkeypatch):
        from core.adapters.payment.stripe import StripeAdapter
        _configure_stripe(monkeypatch)
        a = StripeAdapter()
        params = dict(_VALID_CAPTURE)
        del params["authorization_id"]
        result = a.execute(Capability.PAYMENT_CAPTURE, params)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Bootstrap ──────────────────────────────────────────────


class TestStripeBootstrap:
    def test_register_all_adds_stripe(self):
        from core.adapters.payment.bootstrap import register_all
        status = register_all()
        assert "stripe" in status
        assert "paypal" in status

    def test_stripe_unconfigured_without_env(self):
        from core.adapters.payment.bootstrap import register_all
        status = register_all()
        assert status["stripe"] is False

    def test_stripe_configured_when_env_set(self, monkeypatch):
        from core.adapters.payment.bootstrap import register_all
        _configure_stripe(monkeypatch)
        status = register_all()
        assert status["stripe"] is True

    def test_register_all_idempotent(self):
        from core.adapters.payment.bootstrap import register_all
        register_all()
        register_all()
        assert len([n for n in get_registry().names() if n == "stripe"]) == 1


# ── Router integration ─────────────────────────────────────


class TestStripeRouterIntegration:
    def test_router_routes_to_stripe_when_configured(self, monkeypatch):
        from core.adapters.payment.bootstrap import register_all
        _configure_stripe(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.PAYMENT_REFUND)
        assert chosen.name == "stripe"

    def test_paypal_wins_over_stripe_when_both_configured(self, monkeypatch):
        """PayPal priority=80 > Stripe priority=70, so PayPal wins
        routing ties when both are configured."""
        from core.adapters.payment.bootstrap import register_all
        _configure_stripe(monkeypatch)
        _configure_paypal(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.PAYMENT_REFUND)
        assert chosen.name == "paypal"

    def test_stripe_selected_when_only_stripe_configured(self, monkeypatch):
        """When PayPal is unconfigured, router falls through to Stripe."""
        from core.adapters.payment.bootstrap import register_all
        _configure_stripe(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.PAYMENT_REFUND)
        assert chosen.name == "stripe"

    def test_router_raises_when_no_payment_configured(self):
        from core.adapters.payment.bootstrap import register_all
        register_all()
        with pytest.raises(NoAdapterAvailable):
            get_router().route(Capability.PAYMENT_REFUND)

    def test_end_to_end_refund_records_metrics(self, monkeypatch):
        from core.adapters.payment.bootstrap import register_all
        from core.adapters.payment.stripe import StripeAdapter

        _configure_stripe(monkeypatch)
        register_all()

        adapter = get_registry().get("stripe")
        assert isinstance(adapter, StripeAdapter)

        def fake_post(url, data):
            return {
                "id": "re_E2E",
                "status": "succeeded",
                "amount": 1234,
                "currency": "usd",
            }

        with patch.object(adapter, "_stripe_form_post", side_effect=fake_post):
            result = get_router().execute(
                Capability.PAYMENT_REFUND, dict(_VALID_REFUND),
            )

        assert result.ok
        assert result.adapter == "stripe"
        assert result.capability == "payment_refund"
        assert result.data["refund_id"] == "re_E2E"

        stats = get_metrics().stats_for("stripe")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1
        assert stats["success_rate"] == 1.0
