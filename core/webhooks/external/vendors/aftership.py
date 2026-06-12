"""AfterShip vendor handler.

AfterShip webhook v3:
  - POST to operator-configured URL
  - Headers: 'aftership-hmac-sha256' carries
    base64-encoded HMAC of body
  - Topic: derived from event field
  - Body: { msg: { tracking_number, slug, tag, ... } }

Store identifier: comes via tracking.order_id which we
resolve back to a Shopify shop URL via the order
itself (caller responsibility) OR via the title field
which operators often configure to the shop URL.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

from ..handler import VendorHandler


class AfterShipVendorHandler(VendorHandler):
    name = "aftership"

    def __init__(
        self,
        secret_env: str = "AFTERSHIP_WEBHOOK_SECRET",
    ) -> None:
        self._secret_env = secret_env

    def _secret(self) -> str:
        return os.environ.get(
            self._secret_env, "",
        )

    def verify_hmac(
        self, raw_body: bytes, signature: str,
    ) -> bool:
        secret = self._secret()
        if not secret:
            return True
        if not signature:
            return False
        digest = base64.b64encode(
            hmac.new(
                secret.encode("utf-8"), raw_body,
                hashlib.sha256,
            ).digest(),
        ).decode("ascii")
        return hmac.compare_digest(digest, signature)

    def extract_topic(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        # AfterShip uses 'event' inside msg, like
        # 'tracking_status_updated' or 'tracking_delivered'
        msg = payload.get("msg") or {}
        if isinstance(msg, dict):
            ev = msg.get("event") or ""
            if isinstance(ev, str) and ev:
                return ev
        return str(payload.get("event") or "unknown")

    def extract_store_identifier(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        msg = payload.get("msg") or {}
        if not isinstance(msg, dict):
            return ""
        # Operator convention: set tracking.title to
        # the shop URL when creating trackings
        title = msg.get("title") or ""
        if isinstance(title, str) and "." in title:
            return title
        # Or via custom_fields.shop_url
        custom = msg.get("custom_fields") or {}
        if isinstance(custom, dict):
            shop = custom.get("shop_url") or ""
            if isinstance(shop, str) and shop:
                return shop
        return ""

    def normalise_payload(
        self, topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        msg = payload.get("msg")
        if isinstance(msg, dict):
            return msg
        return payload
