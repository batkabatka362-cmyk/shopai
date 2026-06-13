"""W963-155: Klarna vendor handler.

Klarna webhook docs:
  https://docs.klarna.com/api/order-management/#operation/getMerchantSettings

Klarna is the dominant buy-now-pay-later gateway for
mid-AOV stores. Klarna-side events (captures / refunds /
order cancellations / chargebacks) currently fall
outside ShopAI's observability when a store uses Klarna
as alt payment gateway. This handler closes that gap.

Topics ShopAI listens to:

  order.captured  -> revenue_attribution
  order.refunded  -> returns_management
  order.cancelled -> returns_management +
                     fraud_detection (if pre-capture)
  order.chargeback -> customer_support +
                      fraud_detection
  subscription.cancelled -> churn_prediction

Auth: Klarna signs the request body with HMAC-SHA256 +
base64. Header: 'Klarna-Signature'.

Store identifier:
  Klarna events carry merchant_reference (= Shopify
  order #) at top level OR nested under
  data.order.merchant_reference. Fall back to
  KLARNA_DEFAULT_STORE env when neither is set.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from typing import Any

from ..handler import VendorHandler

logger = logging.getLogger(__name__)


class KlarnaVendorHandler(VendorHandler):
    name = "klarna"

    def __init__(
        self,
        secret_env: str = "KLARNA_WEBHOOK_SECRET",
        default_store_env: str = "KLARNA_DEFAULT_STORE",
    ) -> None:
        self._secret_env = secret_env
        self._default_store_env = default_store_env

    def _secret(self) -> str:
        return os.environ.get(self._secret_env, "")

    def _default_store(self) -> str:
        return os.environ.get(
            self._default_store_env, "",
        )

    def verify_hmac(
        self, raw_body: bytes, signature: str,
    ) -> bool:
        secret = self._secret()
        if not secret:
            return True
        if not signature:
            return False
        expected = base64.b64encode(
            hmac.new(
                secret.encode("utf-8"),
                raw_body, hashlib.sha256,
            ).digest(),
        ).decode("ascii")
        return hmac.compare_digest(expected, signature)

    def extract_topic(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        # Klarna sends event_type at the top level,
        # e.g. 'order.captured'.
        topic = str(
            payload.get("event_type") or "",
        ).strip()
        if not topic:
            return "unknown"
        return topic.lower()

    def extract_store_identifier(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        # Klarna top-level merchant_reference is the
        # Shopify order # the store passed at checkout
        ref = payload.get("merchant_reference")
        if isinstance(ref, str) and ref:
            return ref

        data = payload.get("data")
        if isinstance(data, dict):
            order = data.get("order")
            if isinstance(order, dict):
                ref2 = order.get("merchant_reference")
                if isinstance(ref2, str) and ref2:
                    return ref2

        # Some integrations pass store ID explicitly
        shop = payload.get("shopai_store_id")
        if isinstance(shop, str) and shop:
            return shop

        return self._default_store()

    def normalise_payload(
        self, topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Surface order details as engine-facing payload
        with normalised amount + currency.

        Klarna typical envelope:
          {
            "event_type": "order.captured",
            "merchant_reference": "ord_99",
            "data": {
              "order": {
                "order_id": "klarna_abc",
                "order_amount": 4999,
                "purchase_currency": "USD",
                "status": "CAPTURED",
                ...
              }
            }
          }
        """
        data = payload.get("data")
        if not isinstance(data, dict):
            data = {}
        order = data.get("order")
        if not isinstance(order, dict):
            # Fall back to top-level if no nested order
            order = payload

        # Klarna amounts are in minor units (cents); convert
        # to float for engine consumers
        amount = 0.0
        try:
            raw = order.get("order_amount", 0)
            amount = float(raw) / 100.0
        except (TypeError, ValueError):
            amount = 0.0

        currency = str(
            order.get("purchase_currency", ""),
        ).upper()

        out: dict[str, Any] = {
            "klarna_id": str(order.get("order_id", "")),
            "event_type": topic,
            "amount": amount,
            "currency": currency,
            "status": str(order.get("status", "")),
            "merchant_reference": str(
                payload.get(
                    "merchant_reference",
                    order.get("merchant_reference", ""),
                ),
            ),
            "_klarna_event_id": str(payload.get("id", "")),
        }

        # Chargeback / dispute specific fields
        reason = order.get("chargeback_reason")
        if reason:
            out["chargeback_reason"] = str(reason)

        return out
