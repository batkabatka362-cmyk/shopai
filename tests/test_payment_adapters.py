"""Regression tests for the payment adapter family.

Wave 1 — PayPal only.

Real HTTP calls are forbidden — every test patches either the
adapter's HTTP helpers (``_http_post`` / ``_http_get``) or the
OAuth token fetch so the suite stays hermetic.

Coverage matrix:

  * Capability enum exposes PAYMENT_REFUND / PAYMENT_CAPTURE /
    PAYMENT_LIST_DISPUTES
  * PaymentBaseAdapter validates inputs (transaction_id,
    authorization_id, amount/currency pairing) and rejects
    unknown capabilities
  * PayPalAdapter
        - registry metadata (name, category, capabilities,
          priority, cost)
        - is_configured() requires BOTH client id and secret
        - sandbox vs live base_url switch
        - OAuth2 token fetch + cache + refresh
        - refund happy path (full + partial)
        - capture happy path (full + partial)
        - list_disputes happy path
        - HTTP error mapping (auth, rate limit, validation)
  * Bootstrap
        - register_all adds the adapter, idempotent
        - status map reflects is_configured
  * SmartRouter
        - routes PAYMENT_REFUND to paypal when configured
        - raises NoAdapterAvailable when paypal is not configured
        - end-to-end execute() succeeds and the metrics collector
          captures the outcome (Wave 1 success criterion: a new
          external system is reachable through the router and the
          metrics layer records the call)
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
    """Clear PayPal env + every adapter singleton between tests."""
    for var in (
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


def _configure_paypal(monkeypatch, *, env: str = "sandbox") -> None:
    """Set the env vars + reload the config singleton."""
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "AYxxxxxxxx")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "ELxxxxxxxx")
    monkeypatch.setenv("PAYPAL_ENV", env)
    get_config().reload()


def _stub_token(adapter, *, token: str = "test-token", expires_in: float = 600.0):
    """Patch ``_fetch_token`` so the adapter never hits the real
    OAuth endpoint."""
    return patch.object(
        adapter, "_fetch_token", return_value=(token, expires_in),
    )


_VALID_REFUND = {
    "transaction_id": "9XJ12345AB678901C",
    "amount": "12.34",
    "currency": "USD",
    "reason": "customer_request",
    "note": "Replacement shipped",
    "metadata": {"order_id": "1001"},
}

_VALID_CAPTURE = {
    "authorization_id": "8AB12345CD678901E",
    "amount": "49.99",
    "currency": "USD",
    "is_final_capture": True,
    "note": "Order #1001",
}


# ── Capability enum ─────────────────────────────────────────


class TestPaymentCapabilities:
    def test_payment_capabilities_exist(self):
        assert Capability("payment_refund") is Capability.PAYMENT_REFUND
        assert Capability("payment_capture") is Capability.PAYMENT_CAPTURE
        assert Capability("payment_list_disputes") is Capability.PAYMENT_LIST_DISPUTES


# ── PaymentBaseAdapter validation ───────────────────────────


class TestPaymentBaseAdapter:
    def test_refund_requires_transaction_id(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        params = dict(_VALID_REFUND)
        del params["transaction_id"]
        with _stub_token(a):
            result = a.execute(Capability.PAYMENT_REFUND, params)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "transaction_id" in result.error.reason

    def test_refund_amount_requires_currency(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        params = dict(_VALID_REFUND)
        del params["currency"]
        with _stub_token(a):
            result = a.execute(Capability.PAYMENT_REFUND, params)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "currency" in result.error.reason

    def test_refund_amount_must_be_positive(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        params = dict(_VALID_REFUND)
        params["amount"] = "-5.00"
        with _stub_token(a):
            result = a.execute(Capability.PAYMENT_REFUND, params)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "positive" in result.error.reason

    def test_refund_amount_must_be_numeric(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        params = dict(_VALID_REFUND)
        params["amount"] = "not-a-number"
        with _stub_token(a):
            result = a.execute(Capability.PAYMENT_REFUND, params)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_capture_requires_authorization_id(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        params = dict(_VALID_CAPTURE)
        del params["authorization_id"]
        with _stub_token(a):
            result = a.execute(Capability.PAYMENT_CAPTURE, params)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "authorization_id" in result.error.reason

    def test_capture_amount_requires_currency(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        params = dict(_VALID_CAPTURE)
        del params["currency"]
        with _stub_token(a):
            result = a.execute(Capability.PAYMENT_CAPTURE, params)
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_unknown_capability_returns_validation_error(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        # SEND_EMAIL_TRANSACTIONAL is a real Capability but not
        # one PayPal implements — base class executor must reject
        # it instead of attempting to dispatch.
        with _stub_token(a):
            result = a.execute(
                Capability.SEND_EMAIL_TRANSACTIONAL, {},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── PayPalAdapter ───────────────────────────────────────────


class TestPayPalAdapter:
    def test_metadata(self):
        from core.adapters.payment.paypal import PayPalAdapter
        a = PayPalAdapter()
        assert a.name == "paypal"
        assert a.category == AdapterCategory.PAYMENT
        assert Capability.PAYMENT_REFUND in a.capabilities
        assert Capability.PAYMENT_CAPTURE in a.capabilities
        assert Capability.PAYMENT_LIST_DISPUTES in a.capabilities
        assert a.priority == 80
        assert a.cost_per_call == 0.0

    def test_unconfigured_without_keys(self):
        from core.adapters.payment.paypal import PayPalAdapter
        assert not PayPalAdapter().is_configured()

    def test_unconfigured_with_only_client_id(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        monkeypatch.setenv("PAYPAL_CLIENT_ID", "id")
        get_config().reload()
        assert not PayPalAdapter().is_configured()

    def test_unconfigured_with_only_client_secret(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
        get_config().reload()
        assert not PayPalAdapter().is_configured()

    def test_configured_with_both_credentials(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        assert PayPalAdapter().is_configured()

    def test_sandbox_default_when_env_unset(self, monkeypatch):
        """``PAYPAL_ENV`` unset must default to sandbox so a
        misconfigured deployment never accidentally hits real
        money."""
        from core.adapters.payment.paypal import PayPalAdapter
        monkeypatch.setenv("PAYPAL_CLIENT_ID", "id")
        monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
        get_config().reload()
        a = PayPalAdapter()
        assert "sandbox" in a.base_url
        assert a.is_live() is False

    def test_live_env_switches_base_url(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch, env="live")
        a = PayPalAdapter()
        assert a.base_url == "https://api-m.paypal.com"
        assert a.is_live() is True

    def test_unknown_env_falls_back_to_sandbox(self, monkeypatch):
        """Defensive: anything other than the literal "live"
        must be treated as sandbox."""
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch, env="staging")
        a = PayPalAdapter()
        assert "sandbox" in a.base_url
        assert a.is_live() is False


# ── OAuth2 token cache ──────────────────────────────────────


class TestPayPalTokenCache:
    def test_token_cached_between_calls(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        call_count = {"n": 0}

        def fake_fetch():
            call_count["n"] += 1
            return ("tok-1", 600.0)

        with patch.object(a, "_fetch_token", side_effect=fake_fetch):
            assert a._bearer_token() == "tok-1"
            assert a._bearer_token() == "tok-1"
            assert a._bearer_token() == "tok-1"

        assert call_count["n"] == 1

    def test_expired_token_refreshed(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        # First fetch returns a token that expires "right now"
        # so the second call must refresh.
        call_count = {"n": 0}

        def fake_fetch():
            call_count["n"] += 1
            return (f"tok-{call_count['n']}", 0.0)

        with patch.object(a, "_fetch_token", side_effect=fake_fetch):
            t1 = a._bearer_token()
            t2 = a._bearer_token()

        assert t1 == "tok-1"
        assert t2 == "tok-2"
        assert call_count["n"] == 2

    def test_fetch_token_missing_credentials_raises(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        from core.adapters import AdapterNotConfigured
        # Only client id set — secret missing
        monkeypatch.setenv("PAYPAL_CLIENT_ID", "id")
        get_config().reload()
        a = PayPalAdapter()
        with pytest.raises(AdapterNotConfigured):
            a._fetch_token()


# ── Refund happy path ───────────────────────────────────────


class TestPayPalRefund:
    def test_partial_refund_happy_path(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()

        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {
                "id": "5XY12345AB678901C",
                "status": "COMPLETED",
                "amount": {"value": "12.34", "currency_code": "USD"},
            }

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            result = a.execute(
                Capability.PAYMENT_REFUND, dict(_VALID_REFUND),
            )

        assert result.ok
        assert result.data["refund_id"] == "5XY12345AB678901C"
        assert result.data["status"] == "COMPLETED"
        assert result.data["amount"] == "12.34"
        assert result.data["currency"] == "USD"
        assert result.data["transaction_id"] == "9XJ12345AB678901C"

        assert "/v2/payments/captures/9XJ12345AB678901C/refund" in captured["url"]
        assert "sandbox" in captured["url"]
        assert captured["body"]["amount"] == {
            "value": "12.34", "currency_code": "USD",
        }
        assert captured["body"]["note_to_payer"] == "Replacement shipped"
        assert captured["body"]["invoice_id"] == "1001"
        assert captured["headers"]["Authorization"] == "Bearer test-token"

    def test_full_refund_omits_amount(self, monkeypatch):
        """No ``amount`` in params → no ``amount`` in body. PayPal
        treats an empty body as a full refund."""
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()

        captured = {}

        def fake_post(url, body, headers):
            captured["body"] = body
            return {
                "id": "5FULL",
                "status": "COMPLETED",
                "amount": {},
            }

        params = {"transaction_id": "9XJ12345AB678901C"}

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            result = a.execute(Capability.PAYMENT_REFUND, params)

        assert result.ok
        assert result.data["refund_id"] == "5FULL"
        assert "amount" not in captured["body"]
        assert "note_to_payer" not in captured["body"]

    def test_refund_auth_error_mapped(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        with _stub_token(a), patch.object(
            a, "_http_post",
            side_effect=AdapterAuthError(a.name, "bad token"),
        ):
            result = a.execute(
                Capability.PAYMENT_REFUND, dict(_VALID_REFUND),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_refund_rate_limit_mapped(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()
        with _stub_token(a), patch.object(
            a, "_http_post",
            side_effect=AdapterRateLimited(a.name, "throttled"),
        ):
            result = a.execute(
                Capability.PAYMENT_REFUND, dict(_VALID_REFUND),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)


# ── Capture happy path ──────────────────────────────────────


class TestPayPalCapture:
    def test_partial_capture_happy_path(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()

        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            return {
                "id": "0CD12345EF678901G",
                "status": "COMPLETED",
                "amount": {"value": "49.99", "currency_code": "USD"},
            }

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            result = a.execute(
                Capability.PAYMENT_CAPTURE, dict(_VALID_CAPTURE),
            )

        assert result.ok
        assert result.data["capture_id"] == "0CD12345EF678901G"
        assert result.data["amount"] == "49.99"
        assert result.data["authorization_id"] == "8AB12345CD678901E"
        assert (
            "/v2/payments/authorizations/8AB12345CD678901E/capture"
            in captured["url"]
        )
        assert captured["body"]["final_capture"] is True
        assert captured["body"]["amount"]["value"] == "49.99"

    def test_full_capture_omits_amount(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()

        captured = {}

        def fake_post(url, body, headers):
            captured["body"] = body
            return {
                "id": "FULLCAP",
                "status": "COMPLETED",
                "amount": {},
            }

        params = {"authorization_id": "8AB12345CD678901E"}

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            result = a.execute(Capability.PAYMENT_CAPTURE, params)

        assert result.ok
        assert "amount" not in captured["body"]
        assert captured["body"]["final_capture"] is True


# ── List disputes happy path ────────────────────────────────


class TestPayPalListDisputes:
    def test_list_disputes_happy_path(self, monkeypatch):
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()

        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {
                "items": [
                    {
                        "dispute_id": "PP-D-1",
                        "status": "OPEN",
                        "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
                        "dispute_amount": {
                            "value": "12.34",
                            "currency_code": "USD",
                        },
                        "create_time": "2024-09-01T12:00:00Z",
                    },
                    {
                        "dispute_id": "PP-D-2",
                        "status": "WAITING_FOR_BUYER_RESPONSE",
                        "reason": "UNAUTHORISED",
                        "dispute_amount": {
                            "value": "5.00",
                            "currency_code": "USD",
                        },
                        "create_time": "2024-09-02T12:00:00Z",
                    },
                ],
            }

        with _stub_token(a), patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            result = a.execute(
                Capability.PAYMENT_LIST_DISPUTES,
                {"page_size": 10, "status": "OPEN"},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["disputes"][0]["dispute_id"] == "PP-D-1"
        assert result.data["disputes"][0]["amount"] == "12.34"
        assert "page_size=10" in captured["url"]
        assert "dispute_state=OPEN" in captured["url"]

    def test_list_disputes_clamps_page_size(self, monkeypatch):
        """page_size > 50 must be clamped (PayPal's hard limit)."""
        from core.adapters.payment.paypal import PayPalAdapter
        _configure_paypal(monkeypatch)
        a = PayPalAdapter()

        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {"items": []}

        with _stub_token(a), patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            a.execute(
                Capability.PAYMENT_LIST_DISPUTES,
                {"page_size": 999},
            )

        assert "page_size=50" in captured["url"]


# ── Bootstrap ───────────────────────────────────────────────


class TestPaymentBootstrap:
    def test_register_all_adds_paypal(self):
        from core.adapters.payment.bootstrap import register_all
        status = register_all()
        assert "paypal" in status

    def test_register_all_unconfigured_without_env(self):
        from core.adapters.payment.bootstrap import register_all
        status = register_all()
        assert status["paypal"] is False

    def test_register_all_configured_when_env_set(self, monkeypatch):
        from core.adapters.payment.bootstrap import register_all
        _configure_paypal(monkeypatch)
        status = register_all()
        assert status["paypal"] is True

    def test_register_all_idempotent(self):
        from core.adapters.payment.bootstrap import register_all
        register_all()
        register_all()
        # Only one paypal entry — replace=True keeps the registry
        # at one record.
        assert len([
            n for n in get_registry().names() if n == "paypal"
        ]) == 1


# ── Smart router routing + metrics capture ──────────────────


class TestPaymentRouterIntegration:
    def test_router_routes_payment_refund_to_paypal(self, monkeypatch):
        from core.adapters.payment.bootstrap import register_all
        _configure_paypal(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.PAYMENT_REFUND)
        assert chosen.name == "paypal"

    def test_router_routes_payment_capture_to_paypal(self, monkeypatch):
        from core.adapters.payment.bootstrap import register_all
        _configure_paypal(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.PAYMENT_CAPTURE)
        assert chosen.name == "paypal"

    def test_router_raises_when_paypal_unconfigured(self):
        from core.adapters.payment.bootstrap import register_all
        register_all()
        with pytest.raises(NoAdapterAvailable):
            get_router().route(Capability.PAYMENT_REFUND)

    def test_end_to_end_refund_records_metrics(self, monkeypatch):
        """The Wave 1 success criterion: a brand-new external
        system reachable through the router AND the metrics layer
        captures the outcome.

        We register PayPal, configure it, patch the HTTP helper +
        OAuth fetch so no real network call escapes, then call
        ``router.execute`` and assert that
        ``MetricsCollector.stats_for("paypal")`` shows the
        success."""
        from core.adapters.payment.bootstrap import register_all
        from core.adapters.payment.paypal import PayPalAdapter

        _configure_paypal(monkeypatch)
        register_all()

        adapter = get_registry().get("paypal")
        assert isinstance(adapter, PayPalAdapter)

        def fake_post(url, body, headers):
            return {
                "id": "5XY12345AB678901C",
                "status": "COMPLETED",
                "amount": {"value": "12.34", "currency_code": "USD"},
            }

        with _stub_token(adapter), patch.object(
            adapter, "_http_post", side_effect=fake_post,
        ):
            result = get_router().execute(
                Capability.PAYMENT_REFUND, dict(_VALID_REFUND),
            )

        assert result.ok
        assert result.adapter == "paypal"
        assert result.capability == "payment_refund"
        assert result.data["refund_id"] == "5XY12345AB678901C"

        stats = get_metrics().stats_for("paypal")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1
        assert stats["calls_failure"] == 0
        assert stats["success_rate"] == 1.0

    def test_router_records_failure_metric(self, monkeypatch):
        """A failed call must still flow into the metrics layer
        so the success rate degrades and the router can react."""
        from core.adapters.payment.bootstrap import register_all
        from core.adapters.payment.paypal import PayPalAdapter

        _configure_paypal(monkeypatch)
        register_all()
        adapter = get_registry().get("paypal")
        assert isinstance(adapter, PayPalAdapter)

        with _stub_token(adapter), patch.object(
            adapter, "_http_post",
            side_effect=AdapterAuthError(adapter.name, "bad token"),
        ):
            result = get_router().execute(
                Capability.PAYMENT_REFUND, dict(_VALID_REFUND),
            )

        assert not result.ok
        stats = get_metrics().stats_for("paypal")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_failure"] == 1
        assert stats["calls_success"] == 0
