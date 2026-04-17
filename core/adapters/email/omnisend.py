"""OmnisendAdapter — Omnisend e-commerce marketing email.

Omnisend is built specifically for e-commerce: pre-built
automation workflows for abandoned carts, welcome series,
order confirmations, and win-back campaigns. Tight Shopify
integration makes it a natural fit for ShopAI.

Auth: ``X-API-KEY`` header.
Free tier: 500 emails/month + 500 web push.
Pricing: from $16/month for 6,000 emails.

Reference: https://api-docs.omnisend.com/reference
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import EmailBaseAdapter


class OmnisendAdapter(EmailBaseAdapter):
    name = "omnisend"
    base_url = "https://api.omnisend.com/v3"
    config_alias = "omnisend"

    priority = 65
    cost_per_call = 0.0
    free_tier_monthly_limit = 500

    # ── URL / auth hooks ──────────────────────────────────────

    def _send_url(self) -> str:
        return f"{self.base_url}/campaigns/send"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-API-KEY": self._api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Payload translation ──────────────────────────────────

    def _build_payload(self, message: dict[str, Any]) -> dict[str, Any]:
        """Omnisend transactional email via events API::

            {
              "email": "recipient@example.com",
              "eventName": "transactional",
              "fields": {
                "subject": "...",
                "htmlBody": "...",
                "textBody": "...",
                "fromName": "...",
                "fromEmail": "...",
                "replyTo": "...",
              }
            }
        """
        fields: dict[str, Any] = {
            "subject": message["subject"],
            "fromEmail": message["from_email"],
        }
        if message.get("from_name"):
            fields["fromName"] = message["from_name"]
        if message.get("html"):
            fields["htmlBody"] = message["html"]
        if message.get("text"):
            fields["textBody"] = message["text"]
        if message.get("reply_to"):
            fields["replyTo"] = message["reply_to"]

        payload: dict[str, Any] = {
            "email": message["to"],
            "eventName": "transactional",
            "fields": fields,
        }

        if message.get("tags"):
            payload["tags"] = [str(t) for t in message["tags"]]

        return payload

    # ── Response parsing ──────────────────────────────────────

    def _parse_response(self, raw: Any) -> str:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"unexpected response type: {type(raw).__name__}",
            )
        error = raw.get("error")
        if error:
            raise AdapterError(self.name, f"Omnisend error: {error}")
        return str(raw.get("eventID", "") or raw.get("id", "") or "omnisend-accepted")
