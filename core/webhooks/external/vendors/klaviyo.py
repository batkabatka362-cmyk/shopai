"""W963-151: Klaviyo vendor handler.

Klaviyo webhook docs:
  https://developers.klaviyo.com/en/reference/webhooks_api_overview

Klaviyo Webhooks API (2024-10+) signs the request body
with HMAC-SHA256 + base64. Header:
'X-Klaviyo-Webhook-Signature'.

Topics ShopAI listens to:

  unsubscribe          -> customer_outreach (re-engagement
                          throttle) + customer_segmentation
  bounce               -> customer_outreach (bounce
                          tracking) + email_marketing
                          (deliverability signal)
  spam_report          -> fraud_detection (suspicious
                          recipient) + customer_outreach
  metric.ordered_product -> revenue_attribution (cross-
                          check vs Shopify)
  metric.placed_order  -> revenue_attribution
  open                 -> customer_outreach (engagement
                          signal)
  click                -> customer_outreach (engagement
                          + click-through attribution)

Store identifier: Klaviyo events carry the metric or
profile object. Operator convention: set profile
properties['shopai_store_id'] OR profile properties
['shop_url'] when syncing customers from Shopify.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

from ..handler import VendorHandler


class KlaviyoVendorHandler(VendorHandler):
    name = "klaviyo"

    def __init__(
        self,
        secret_env: str = "KLAVIYO_WEBHOOK_SECRET",
    ) -> None:
        self._secret_env = secret_env

    def _secret(self) -> str:
        return os.environ.get(self._secret_env, "")

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
        # Klaviyo Webhooks API surface (2024-10+):
        # {type: 'event', attributes: {metric: {name:
        # 'Unsubscribed'}}}
        # Older webhook subscriptions emit
        # {event_name: 'unsubscribe'}.
        # We accept either.
        attrs = payload.get("attributes") or {}
        if isinstance(attrs, dict):
            metric = attrs.get("metric") or {}
            if isinstance(metric, dict):
                name = (
                    metric.get("name") or ""
                ).strip()
                if name:
                    return _normalise_topic(name)
        ev = (
            payload.get("event_name")
            or payload.get("type")
            or ""
        )
        return _normalise_topic(str(ev or "unknown"))

    def extract_store_identifier(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        """Look for shop_url or shopai_store_id in
        profile properties OR custom event properties."""
        # 2024+ shape: attributes.profile.properties
        attrs = payload.get("attributes") or {}
        if isinstance(attrs, dict):
            profile = attrs.get("profile") or {}
            if isinstance(profile, dict):
                props = (
                    profile.get("properties") or {}
                )
                if isinstance(props, dict):
                    sid = self._extract_from_props(
                        props,
                    )
                    if sid:
                        return sid
            # Event-level custom properties
            event_props = (
                attrs.get("event_properties") or {}
            )
            if isinstance(event_props, dict):
                sid = self._extract_from_props(
                    event_props,
                )
                if sid:
                    return sid
        # Legacy shape: payload.person.shop_url
        person = payload.get("person") or {}
        if isinstance(person, dict):
            sid = self._extract_from_props(person)
            if sid:
                return sid
        return ""

    @staticmethod
    def _extract_from_props(
        props: dict[str, Any],
    ) -> str:
        shop = (
            props.get("shop_url")
            or props.get("shopai_store_id")
            or props.get("store_id")
            or ""
        )
        if isinstance(shop, str) and shop:
            return shop
        return ""

    def normalise_payload(
        self, topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Flatten the Klaviyo event so engines see
        a simple {profile, properties, value, ...}
        dict rather than the {type, attributes:
        {profile, metric, ...}} envelope."""
        attrs = payload.get("attributes")
        if not isinstance(attrs, dict):
            return payload
        profile = attrs.get("profile") or {}
        metric = attrs.get("metric") or {}
        out: dict[str, Any] = {
            "topic_raw": (
                metric.get("name", "")
                if isinstance(metric, dict) else ""
            ),
            "profile": (
                profile
                if isinstance(profile, dict) else {}
            ),
            "event_properties": (
                attrs.get("event_properties") or {}
            ),
            "value": attrs.get("value", 0),
            "timestamp": attrs.get(
                "timestamp",
                attrs.get("datetime", ""),
            ),
        }
        return out


def _normalise_topic(raw: str) -> str:
    """Map vendor-specific names to topic constants we
    use in EVENT_ENGINE_MAP."""
    name = raw.strip().lower().replace(" ", "_")
    # Klaviyo metric names that differ from our map keys
    aliases = {
        "unsubscribed": "unsubscribe",
        "marked_email_as_spam": "spam_report",
        "received_email": "delivered",
        "opened_email": "open",
        "clicked_email": "click",
        "placed_order": "metric.placed_order",
        "ordered_product": "metric.ordered_product",
        "bounced_email": "bounce",
    }
    return aliases.get(name, name)
