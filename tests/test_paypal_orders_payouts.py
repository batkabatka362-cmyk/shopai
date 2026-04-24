"""PayPal Wave 2 regression — Orders v2 + Payouts + Balance + Txns.

Mock-HTTP only. Every test patches ``_http_post`` / ``_http_get``
+ ``_fetch_token`` so no real network call escapes.

Coverage:
  * create_order — amount validation, body shape, approve_url
                   parsing, reference_id / description /
                   application_context branches
  * get_order    — path, parser
  * capture_order — empty-body POST, capture_id parsing
                    (§4b.D idempotent)
  * payout       — items validation (non-empty, dict per row,
                   email + positive amount), batch_id required,
                   body shape, parser
  * list_transactions — default 7-day window, urlencoded params,
                        page_size clamp
  * get_balance  — optional currency filter, parser
  * parsers      — non-dict raises, empty links / captures safe
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterValidationError,
    Capability,
    get_config,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)
from core.adapters.errors import AdapterError


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_ENV",
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
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "AYxxxxxxxx")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "ELxxxxxxxx")
    monkeypatch.setenv("PAYPAL_ENV", env)
    get_config().reload()


def _stub_token(adapter):
    return patch.object(
        adapter, "_fetch_token", return_value=("test-token", 600.0),
    )


def _new_adapter(monkeypatch):
    from core.adapters.payment.paypal import PayPalAdapter
    _configure_paypal(monkeypatch)
    return PayPalAdapter()


# ── Capability enum ─────────────────────────────────────────


class TestNewCapabilities:
    def test_all_six_capabilities_exist(self):
        assert (
            Capability("payment_create_order")
            is Capability.PAYMENT_CREATE_ORDER
        )
        assert (
            Capability("payment_get_order")
            is Capability.PAYMENT_GET_ORDER
        )
        assert (
            Capability("payment_capture_order")
            is Capability.PAYMENT_CAPTURE_ORDER
        )
        assert Capability("payment_payout") is Capability.PAYMENT_PAYOUT
        assert (
            Capability("payment_list_transactions")
            is Capability.PAYMENT_LIST_TRANSACTIONS
        )
        assert (
            Capability("payment_get_balance")
            is Capability.PAYMENT_GET_BALANCE
        )

    def test_paypal_exposes_all_six(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        for cap in (
            Capability.PAYMENT_CREATE_ORDER,
            Capability.PAYMENT_GET_ORDER,
            Capability.PAYMENT_CAPTURE_ORDER,
            Capability.PAYMENT_PAYOUT,
            Capability.PAYMENT_LIST_TRANSACTIONS,
            Capability.PAYMENT_GET_BALANCE,
        ):
            assert cap in a.capabilities


# ── create_order ────────────────────────────────────────────


class TestCreateOrder:
    def test_amount_required(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        with _stub_token(a):
            result = a.execute(
                Capability.PAYMENT_CREATE_ORDER, {},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "amount" in result.error.reason

    def test_amount_must_be_numeric(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        with _stub_token(a):
            result = a.execute(
                Capability.PAYMENT_CREATE_ORDER,
                {"amount": "nope"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_amount_must_be_positive(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        with _stub_token(a):
            result = a.execute(
                Capability.PAYMENT_CREATE_ORDER,
                {"amount": 0},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_happy_path_minimal_body(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            return {
                "id": "ORDER-1",
                "status": "CREATED",
                "links": [
                    {"rel": "self", "href": "https://x/self"},
                    {"rel": "approve", "href": "https://x/approve"},
                ],
            }

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            result = a.execute(
                Capability.PAYMENT_CREATE_ORDER,
                {"amount": 29.9},
            )

        assert result.ok
        assert result.data["order_id"] == "ORDER-1"
        assert result.data["status"] == "CREATED"
        assert result.data["approve_url"] == "https://x/approve"
        assert captured["url"].endswith("/v2/checkout/orders")
        assert "sandbox" in captured["url"]
        assert captured["body"]["intent"] == "CAPTURE"
        unit = captured["body"]["purchase_units"][0]
        assert unit["amount"] == {
            "currency_code": "USD", "value": "29.90",
        }
        assert "reference_id" not in unit
        assert "application_context" not in captured["body"]

    def test_reference_id_and_description_on_unit(
        self, monkeypatch,
    ):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_post(url, body, headers):
            captured["body"] = body
            return {"id": "ORDER-2", "status": "CREATED"}

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            result = a.execute(
                Capability.PAYMENT_CREATE_ORDER,
                {
                    "amount": 10,
                    "currency": "eur",
                    "reference_id": "SH-1001",
                    "description": "Cozy lamp bundle",
                },
            )

        assert result.ok
        unit = captured["body"]["purchase_units"][0]
        assert unit["reference_id"] == "SH-1001"
        assert unit["description"] == "Cozy lamp bundle"
        assert unit["amount"]["currency_code"] == "EUR"

    def test_application_context_populated(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_post(url, body, headers):
            captured["body"] = body
            return {"id": "ORDER-3", "status": "CREATED"}

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            a.execute(
                Capability.PAYMENT_CREATE_ORDER,
                {
                    "amount": 10,
                    "return_url": "https://shop/ok",
                    "cancel_url": "https://shop/cancel",
                    "brand_name": "Deguar",
                },
            )

        ac = captured["body"]["application_context"]
        assert ac["return_url"] == "https://shop/ok"
        assert ac["cancel_url"] == "https://shop/cancel"
        assert ac["brand_name"] == "Deguar"

    def test_payer_action_rel_also_recognised(self, monkeypatch):
        """Some PayPal responses use ``payer-action`` rather than
        ``approve`` for the buyer redirect URL."""
        a = _new_adapter(monkeypatch)

        def fake_post(url, body, headers):
            return {
                "id": "ORDER-4",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [
                    {"rel": "self", "href": "https://x/self"},
                    {
                        "rel": "payer-action",
                        "href": "https://x/payer",
                    },
                ],
            }

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            result = a.execute(
                Capability.PAYMENT_CREATE_ORDER, {"amount": 5},
            )

        assert result.ok
        assert result.data["approve_url"] == "https://x/payer"


# ── get_order ───────────────────────────────────────────────


class TestGetOrder:
    def test_requires_order_id(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        with _stub_token(a):
            result = a.execute(Capability.PAYMENT_GET_ORDER, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_happy_path(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {"id": "ORDER-5", "status": "APPROVED"}

        with _stub_token(a), patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            result = a.execute(
                Capability.PAYMENT_GET_ORDER,
                {"order_id": "ORDER-5"},
            )

        assert result.ok
        assert result.data["order_id"] == "ORDER-5"
        assert result.data["status"] == "APPROVED"
        assert captured["url"].endswith(
            "/v2/checkout/orders/ORDER-5",
        )

    def test_order_id_whitespace_rejected(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        with _stub_token(a):
            result = a.execute(
                Capability.PAYMENT_GET_ORDER,
                {"order_id": "   "},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── capture_order ───────────────────────────────────────────


class TestCaptureOrder:
    def test_requires_order_id(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        with _stub_token(a):
            result = a.execute(
                Capability.PAYMENT_CAPTURE_ORDER, {},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_happy_path_empty_body(self, monkeypatch):
        """Capture intent=CAPTURE orders by POST with empty body.
        Parser extracts capture_id from purchase_units[0].payments
        .captures[0]."""
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            return {
                "id": "ORDER-7",
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAP-99",
                                    "amount": {
                                        "value": "29.90",
                                        "currency_code": "USD",
                                    },
                                },
                            ],
                        },
                    },
                ],
            }

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            result = a.execute(
                Capability.PAYMENT_CAPTURE_ORDER,
                {"order_id": "ORDER-7"},
            )

        assert result.ok
        assert result.data["order_id"] == "ORDER-7"
        assert result.data["status"] == "COMPLETED"
        assert result.data["capture_id"] == "CAP-99"
        assert result.data["captured_amount"] == "29.90"
        assert result.data["captured_currency"] == "USD"
        assert captured["url"].endswith(
            "/v2/checkout/orders/ORDER-7/capture",
        )
        assert captured["body"] is None


# ── payout ──────────────────────────────────────────────────


class TestPayout:
    def _valid_payload(self) -> dict:
        return {
            "batch_id": "BATCH-001",
            "email_subject": "Your Deguar payout",
            "items": [
                {
                    "recipient_email": "seller@example.com",
                    "amount": "25.00",
                    "currency": "usd",
                    "note": "affiliate payout",
                    "sender_item_id": "SH-AFF-7",
                },
            ],
        }

    def test_requires_non_empty_items(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        for payload in ({}, {"items": []}, {"items": "oops"}):
            with _stub_token(a):
                payload = dict(payload)
                payload["batch_id"] = "B1"
                result = a.execute(
                    Capability.PAYMENT_PAYOUT, payload,
                )
            assert not result.ok
            assert isinstance(result.error, AdapterValidationError)

    def test_requires_batch_id(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        payload = self._valid_payload()
        del payload["batch_id"]
        with _stub_token(a):
            result = a.execute(
                Capability.PAYMENT_PAYOUT, payload,
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "batch_id" in result.error.reason

    def test_item_must_be_dict(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        payload = self._valid_payload()
        payload["items"] = ["not-a-dict"]
        with _stub_token(a):
            result = a.execute(
                Capability.PAYMENT_PAYOUT, payload,
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_item_requires_email(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        payload = self._valid_payload()
        payload["items"][0].pop("recipient_email")
        with _stub_token(a):
            result = a.execute(
                Capability.PAYMENT_PAYOUT, payload,
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "recipient_email" in result.error.reason

    def test_item_amount_must_be_positive(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        payload = self._valid_payload()
        payload["items"][0]["amount"] = "-5"
        with _stub_token(a):
            result = a.execute(
                Capability.PAYMENT_PAYOUT, payload,
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_item_amount_must_be_numeric(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        payload = self._valid_payload()
        payload["items"][0]["amount"] = "not-a-number"
        with _stub_token(a):
            result = a.execute(
                Capability.PAYMENT_PAYOUT, payload,
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_happy_path(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            return {
                "batch_header": {
                    "payout_batch_id": "PB-1",
                    "batch_status": "PENDING",
                    "sender_batch_header": {
                        "sender_batch_id": "BATCH-001",
                    },
                },
                "items": [{"id": "x1"}, {"id": "x2"}],
            }

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            result = a.execute(
                Capability.PAYMENT_PAYOUT, self._valid_payload(),
            )

        assert result.ok
        assert result.data["payout_batch_id"] == "PB-1"
        assert result.data["batch_status"] == "PENDING"
        assert result.data["sender_batch_id"] == "BATCH-001"
        assert result.data["items_count"] == 2
        assert captured["url"].endswith("/v1/payments/payouts")
        header = captured["body"]["sender_batch_header"]
        assert header["sender_batch_id"] == "BATCH-001"
        assert header["email_subject"] == "Your Deguar payout"
        row = captured["body"]["items"][0]
        assert row["recipient_type"] == "EMAIL"
        assert row["receiver"] == "seller@example.com"
        assert row["amount"] == {
            "value": "25.00", "currency": "USD",
        }
        assert row["note"] == "affiliate payout"
        assert row["sender_item_id"] == "SH-AFF-7"

    def test_default_email_subject(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_post(url, body, headers):
            captured["body"] = body
            return {"batch_header": {}}

        payload = self._valid_payload()
        del payload["email_subject"]

        with _stub_token(a), patch.object(
            a, "_http_post", side_effect=fake_post,
        ):
            a.execute(Capability.PAYMENT_PAYOUT, payload)

        assert captured["body"]["sender_batch_header"][
            "email_subject"
        ] == "You have a payment from Deguar"


# ── list_transactions ───────────────────────────────────────


class TestListTransactions:
    def test_default_window_seven_days(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {"transaction_details": []}

        with _stub_token(a), patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            result = a.execute(
                Capability.PAYMENT_LIST_TRANSACTIONS, {},
            )

        assert result.ok
        # URL-encoded default params present
        assert "/v1/reporting/transactions?" in captured["url"]
        assert "start_date=" in captured["url"]
        assert "end_date=" in captured["url"]
        assert "page_size=50" in captured["url"]
        assert "fields=" in captured["url"]

    def test_page_size_clamped(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {"transaction_details": []}

        with _stub_token(a), patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            a.execute(
                Capability.PAYMENT_LIST_TRANSACTIONS,
                {"page_size": 9999},
            )

        assert "page_size=500" in captured["url"]

    def test_page_size_non_numeric_falls_back(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {"transaction_details": []}

        with _stub_token(a), patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            a.execute(
                Capability.PAYMENT_LIST_TRANSACTIONS,
                {"page_size": "not-a-number"},
            )

        assert "page_size=50" in captured["url"]

    def test_custom_dates_passthrough(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {"transaction_details": []}

        with _stub_token(a), patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            a.execute(
                Capability.PAYMENT_LIST_TRANSACTIONS,
                {
                    "start_date": "2026-01-01T00:00:00-0000",
                    "end_date": "2026-01-31T00:00:00-0000",
                    "page_size": 25,
                },
            )

        url = captured["url"]
        assert "start_date=2026-01-01T00" in url
        assert "end_date=2026-01-31T00" in url
        assert "page_size=25" in url

    def test_parse_transactions_happy_path(self, monkeypatch):
        a = _new_adapter(monkeypatch)

        def fake_get(url, headers):
            return {
                "transaction_details": [
                    {
                        "transaction_info": {
                            "transaction_id": "T-1",
                            "transaction_status": "S",
                            "transaction_event_code": "T0006",
                            "transaction_amount": {
                                "value": "42.00",
                                "currency_code": "USD",
                            },
                            "transaction_initiation_date":
                                "2026-04-01T00:00:00Z",
                        },
                        "payer_info": {
                            "email_address": "buyer@x.com",
                            "payer_name": {
                                "alternate_full_name": "Jane",
                            },
                        },
                    },
                    "malformed-row",
                ],
            }

        with _stub_token(a), patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            result = a.execute(
                Capability.PAYMENT_LIST_TRANSACTIONS, {},
            )

        assert result.ok
        # Malformed row is skipped silently.
        assert result.data["count"] == 1
        row = result.data["transactions"][0]
        assert row["id"] == "T-1"
        assert row["status"] == "S"
        assert row["event_code"] == "T0006"
        assert row["amount"] == "42.00"
        assert row["currency"] == "USD"
        assert row["payer_email"] == "buyer@x.com"
        assert row["payer_name"] == "Jane"


# ── get_balance ─────────────────────────────────────────────


class TestGetBalance:
    def test_no_currency_filter(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {
                "balances": [
                    {
                        "currency": "USD",
                        "primary": True,
                        "total_balance": {"value": "123.45"},
                        "available_balance": {"value": "120.00"},
                    },
                    {
                        "currency": "EUR",
                        "primary": False,
                        "total_balance": {"value": "40.00"},
                        "available_balance": {"value": "40.00"},
                    },
                ],
                "as_of_time": "2026-04-24T00:00:00Z",
            }

        with _stub_token(a), patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            result = a.execute(
                Capability.PAYMENT_GET_BALANCE, {},
            )

        assert result.ok
        assert captured["url"].endswith("/v1/reporting/balances")
        assert result.data["count"] == 2
        assert (
            result.data["as_of_time"] == "2026-04-24T00:00:00Z"
        )
        usd = result.data["balances"][0]
        assert usd["currency"] == "USD"
        assert usd["primary"] is True
        assert usd["total_value"] == "123.45"
        assert usd["available_value"] == "120.00"

    def test_currency_filter_urlencoded(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        captured = {}

        def fake_get(url, headers):
            captured["url"] = url
            return {"balances": []}

        with _stub_token(a), patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            a.execute(
                Capability.PAYMENT_GET_BALANCE, {"currency": "eur"},
            )

        assert "currency_code=EUR" in captured["url"]


# ── Parser edge cases ──────────────────────────────────────


class TestParserEdgeCases:
    def test_parse_order_rejects_non_dict(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        with pytest.raises(AdapterError):
            a._parse_order("oops")

    def test_parse_order_empty_links_and_units(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        out = a._parse_order(
            {"id": "X", "status": "CREATED"},
        )
        assert out["order_id"] == "X"
        assert out["approve_url"] == ""
        assert out["capture_id"] == ""
        assert out["captured_amount"] == ""

    def test_parse_order_ignores_malformed_link_entries(
        self, monkeypatch,
    ):
        a = _new_adapter(monkeypatch)
        out = a._parse_order({
            "id": "X",
            "status": "CREATED",
            "links": [
                "not-a-dict",
                {"rel": "approve", "href": "https://good"},
            ],
        })
        assert out["approve_url"] == "https://good"

    def test_parse_payout_rejects_non_dict(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        with pytest.raises(AdapterError):
            a._parse_payout(["nope"])

    def test_parse_payout_handles_missing_header(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        out = a._parse_payout({})
        assert out["payout_batch_id"] == ""
        assert out["batch_status"] == ""
        assert out["sender_batch_id"] == ""
        assert out["items_count"] == 0

    def test_parse_transactions_rejects_non_dict(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        with pytest.raises(AdapterError):
            a._parse_transactions("oops")

    def test_parse_balance_rejects_non_dict(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        with pytest.raises(AdapterError):
            a._parse_balance(None)

    def test_parse_balance_empty_list(self, monkeypatch):
        a = _new_adapter(monkeypatch)
        out = a._parse_balance({"balances": []})
        assert out["count"] == 0
        assert out["balances"] == []
