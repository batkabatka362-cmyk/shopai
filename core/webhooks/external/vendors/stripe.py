"""W963-150: Stripe vendor handler for unified webhook
ingestion.

Stripe webhook docs:
  https://stripe.com/docs/webhooks/signatures

Auth: HMAC-SHA256 of the timestamp + body, header
'Stripe-Signature' format: 't=<unix>,v1=<sig>,v0=<old>'.

Topics relevant to ShopAI:
  charge.dispute.created      -> fraud_detection +
                                  refund_processing
  charge.dispute.closed       -> refund_processing
                                  (final outcome)
  charge.refunded             -> returns_management
                                  (parallel to Shopify
                                  webhook for cross-
                                  check)
  payout.created              -> revenue_attribution
                                  (cash-flow signal)
  payment_intent.payment_failed -> customer_support
                                  (failed checkout
                                  recovery)

Store identifier: Stripe events don't directly carry the
shop URL. Operators must wire the Stripe webhook to a
per-store endpoint URL pattern (recommended) OR include
the shop URL in event metadata. We extract from
metadata.shop_url when present.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any

from ..handler import VendorHandler

logger = logging.getLogger(__name__)


# Allowed clock skew when verifying Stripe signature
# timestamps. Stripe recommends 5 minutes.
_STRIPE_TOLERANCE_SECONDS = 300


def _parse_signature_header(
    header: str,
) -> tuple[int, list[str]]:
    """Parse Stripe-Signature into (timestamp,
    [signature]). Returns (0, []) on malformed input."""
    if not header:
        return 0, []
    ts = 0
    sigs: list[str] = []
    for chunk in header.split(","):
        if "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "t":
            try:
                ts = int(v)
            except (TypeError, ValueError):
                ts = 0
        elif k.startswith("v"):
            sigs.append(v)
    return ts, sigs


class StripeVendorHandler(VendorHandler):
    """Stripe webhook handler."""

    name = "stripe"

    def __init__(
        self,
        secret_env: str = "STRIPE_WEBHOOK_SECRET",
    ) -> None:
        self._secret_env = secret_env

    def _secret(self) -> str:
        return os.environ.get(self._secret_env, "")

    def verify_hmac(
        self, raw_body: bytes,
        signature: str,
    ) -> bool:
        """Stripe's verify scheme: hmac-sha256(secret,
        f'{timestamp}.{body}'). Compare against each
        signature listed in the header. Reject if the
        timestamp is older than _STRIPE_TOLERANCE."""
        secret = self._secret()
        if not secret:
            # No secret = skip verification (operator
            # opt-in)
            return True
        timestamp, sigs = _parse_signature_header(
            signature,
        )
        if not timestamp or not sigs:
            return False
        # Reject ancient timestamps (replay protection)
        age = abs(int(time.time()) - timestamp)
        if age > _STRIPE_TOLERANCE_SECONDS:
            logger.debug(
                "stripe webhook timestamp too old: "
                "%d seconds skew", age,
            )
            return False
        signed_payload = (
            f"{timestamp}."
            .encode("utf-8") + raw_body
        )
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        for s in sigs:
            if hmac.compare_digest(expected, s):
                return True
        return False

    def extract_topic(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        # Stripe events have 'type' at the top level
        # like 'charge.dispute.created'
        topic = str(payload.get("type") or "").strip()
        if not topic:
            return "unknown"
        return topic

    def extract_store_identifier(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        """Stripe events embed the object that
        triggered them under data.object. Some objects
        carry metadata.shop_url (operator convention)
        or metadata.shopai_store_id."""
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return ""
        obj = data.get("object") or {}
        if not isinstance(obj, dict):
            return ""
        meta = obj.get("metadata") or {}
        if not isinstance(meta, dict):
            return ""
        # Operator's preferred field is shop_url; fall
        # back to direct sid if set
        shop = (
            meta.get("shop_url")
            or meta.get("shopai_store_id")
            or ""
        )
        if not isinstance(shop, str):
            return ""
        return shop

    def normalise_payload(
        self, topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Expose data.object as the engine-facing
        payload (omit the Stripe event wrapper)."""
        data = payload.get("data") or {}
        if isinstance(data, dict):
            obj = data.get("object")
            if isinstance(obj, dict):
                # Surface Stripe event id for
                # downstream idempotency tracking
                obj = dict(obj)
                obj["_stripe_event_id"] = payload.get(
                    "id", "",
                )
                obj["_stripe_event_type"] = topic
                return obj
        return payload
