"""W963-154: PayPal vendor handler.

PayPal Webhooks API docs:
  https://developer.paypal.com/api/rest/webhooks/event-names/

For stores using PayPal as alternate payment gateway
alongside Shopify Payments, PayPal-side events (disputes,
chargebacks, captures) currently fall outside ShopAI's
observability. This handler closes that gap.

Topics ShopAI listens to:

  payment.capture.completed -> revenue_attribution
                              (cross-check vs Shopify)
  payment.capture.refunded -> returns_management
  payment.capture.reversed -> returns_management +
                              fraud_detection
  customer.dispute.created -> customer_support +
                              fraud_detection
  customer.dispute.resolved -> returns_management
  billing.subscription.cancelled -> churn_prediction

Auth (W963-154 v1):
  PayPal Webhooks v2 sign with a public-key chain via
  PAYPAL-TRANSMISSION-SIG header. Full crypto verify
  requires a PayPal API client (POST to
  /v1/notifications/verify-webhook-signature with
  credentials). For initial ship we accept events when
  PAYPAL_WEBHOOK_ID env matches the transmission_id
  header prefix. Set PAYPAL_WEBHOOK_ID="" to disable
  the check (only safe behind an IP allowlist at the
  reverse proxy).

  Future enhancement: full PayPal-side verify when
  PaypalAdapter capability lands.

Store identifier:
  PayPal events carry resource.custom_id (custom
  checkout metadata = recommended convention:
  shopai_store_id) OR resource.invoice_number (Shopify
  order #). Fall back to PAYPAL_DEFAULT_STORE env when
  neither is set.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from ..handler import VendorHandler

logger = logging.getLogger(__name__)


class PayPalVendorHandler(VendorHandler):
    name = "paypal"

    def __init__(
        self,
        webhook_id_env: str = "PAYPAL_WEBHOOK_ID",
        default_store_env: str = "PAYPAL_DEFAULT_STORE",
    ) -> None:
        self._webhook_id_env = webhook_id_env
        self._default_store_env = default_store_env

    def _webhook_id(self) -> str:
        return os.environ.get(self._webhook_id_env, "")

    def _default_store(self) -> str:
        return os.environ.get(
            self._default_store_env, "",
        )

    def verify_hmac(
        self, raw_body: bytes, signature: str,
    ) -> bool:
        """v1 verification: webhook_id match.

        See module docstring for limitation rationale +
        future enhancement plan.
        """
        webhook_id = self._webhook_id()
        if not webhook_id:
            # Disabled -- accept all (operator opted out).
            return True
        # PayPal transmission_id format: "<webhook_id>-<sub>"
        # Some integrations send just <webhook_id>.
        if not signature:
            return False
        return signature.startswith(webhook_id)

    def extract_topic(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        # PayPal v2: {event_type: "PAYMENT.CAPTURE.COMPLETED"}
        topic = str(payload.get("event_type") or "").strip()
        if not topic:
            return "unknown"
        # Normalise to lower-case dotted form so EVENT_ENGINE_MAP
        # keys stay consistent with other vendors.
        return topic.lower()

    def extract_store_identifier(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        resource = payload.get("resource")
        if not isinstance(resource, dict):
            return self._default_store()

        # Preferred: explicit shopai_store_id set as
        # custom_id during checkout
        custom_id = resource.get("custom_id")
        if isinstance(custom_id, str) and custom_id:
            return custom_id

        # Shopify order # in invoice_number; caller's
        # StoreManager resolves
        invoice = resource.get("invoice_number")
        if isinstance(invoice, str) and invoice:
            return invoice

        # Dispute events nest the transactions deeper
        disputed = resource.get("disputed_transactions")
        if isinstance(disputed, list) and disputed:
            head = disputed[0]
            if isinstance(head, dict):
                txn_inv = head.get("invoice_number")
                if isinstance(txn_inv, str) and txn_inv:
                    return txn_inv

        return self._default_store()

    def normalise_payload(
        self, topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Surface the resource object as the engine-facing
        payload, with normalised amount + currency."""
        resource = payload.get("resource")
        if not isinstance(resource, dict):
            return payload

        amount_obj = resource.get("amount") or {}
        if not isinstance(amount_obj, dict):
            amount_obj = {}
        amount = 0.0
        try:
            amount = float(amount_obj.get("value", 0))
        except (TypeError, ValueError):
            amount = 0.0
        currency = str(amount_obj.get(
            "currency_code", "",
        )).upper()

        out: dict[str, Any] = {
            "paypal_id": str(resource.get("id", "")),
            "event_type": topic,
            "amount": amount,
            "currency": currency,
            "status": str(resource.get("status", "")),
            "invoice_number": str(
                resource.get("invoice_number", ""),
            ),
            "custom_id": str(resource.get("custom_id", "")),
            "create_time": str(payload.get("create_time", "")),
            "_paypal_event_id": str(payload.get("id", "")),
        }

        # Dispute-specific fields
        reason = resource.get("reason")
        if reason:
            out["dispute_reason"] = str(reason)
        outcome = resource.get("dispute_outcome")
        if isinstance(outcome, dict):
            out["dispute_outcome"] = str(
                outcome.get("outcome_code", ""),
            )

        return out
