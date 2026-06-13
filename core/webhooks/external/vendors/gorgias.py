"""Gorgias vendor handler.

Gorgias webhook topics:
  ticket_created
  ticket_updated
  message_created
  customer_created

Auth: HMAC-SHA256 of raw body with shared secret,
header: `X-Gorgias-Signature` (hex).

Store identifier: extract from ticket.uri or the
configured per-store gorgias_subdomain mapping.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from ..handler import VendorHandler


class GorgiasVendorHandler(VendorHandler):
    name = "gorgias"

    def __init__(
        self,
        secret_env: str = "GORGIAS_WEBHOOK_SECRET",
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
            # No secret configured -> skip verification
            return True
        if not signature:
            return False
        digest = hmac.new(
            secret.encode("utf-8"), raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(digest, signature)

    def extract_topic(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        # Gorgias sends event type in X-Gorgias-Topic
        # header (also can be in payload.event)
        topic = (
            headers.get("X-Gorgias-Topic")
            or headers.get("x-gorgias-topic")
            or str(payload.get("event") or "")
        ).strip()
        return topic or "unknown"

    def extract_store_identifier(
        self, payload: dict[str, Any],
        headers: dict[str, str],
    ) -> str:
        # Gorgias account_id (Subdomain) lives in
        # payload.account.account_id OR in
        # ticket.via.address.subdomain. Operators must
        # have configured the store's subdomain via
        # SHOPAI_STORE_<SID>_GORGIAS_SUBDOMAIN -- we
        # return the subdomain and let the resolver map
        # back to sid via reverse lookup of operator
        # config.
        # For now: derive from ticket.via.uri host.
        ticket = payload.get("ticket") or payload
        if not isinstance(ticket, dict):
            return ""
        # Try ticket.via.uri
        via = ticket.get("via") or {}
        if isinstance(via, dict):
            uri = via.get("uri") or ""
            if isinstance(uri, str) and uri:
                return uri
        # Try account.id
        acct = payload.get("account") or {}
        if isinstance(acct, dict):
            sub = acct.get("subdomain") or ""
            if isinstance(sub, str) and sub:
                return f"{sub}.gorgias.com"
        return ""

    def normalise_payload(
        self, topic: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        # Pass the ticket sub-object through if present,
        # otherwise raw payload.
        ticket = payload.get("ticket")
        if isinstance(ticket, dict):
            return ticket
        return payload
