"""PostmarkAdapter — Postmark transactional email.

Postmark specializes in transactional email delivery with
industry-leading delivery speed (average <10 seconds to inbox).
Ideal for time-sensitive notifications: order confirmations,
shipping updates, password resets.

Auth: ``X-Postmark-Server-Token`` header.
Free tier: 100 emails/month (test mode).
Pricing: from $15/month for 10,000 emails.

Reference: https://postmarkapp.com/developer/api/email-api
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import EmailBaseAdapter


class PostmarkAdapter(EmailBaseAdapter):
    name = "postmark"
    base_url = "https://api.postmarkapp.com"
    config_alias = "postmark"

    priority = 70
    cost_per_call = 0.0
    free_tier_monthly_limit = 100

    # ── URL / auth hooks ──────────────────────────────────────

    def _send_url(self) -> str:
        return f"{self.base_url}/email"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-Postmark-Server-Token": self._api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Payload translation ──────────────────────────────────

    def _build_payload(self, message: dict[str, Any]) -> dict[str, Any]:
        """Postmark expects::

            {
              "From":     "sender@example.com",
              "To":       "recipient@example.com",
              "Subject":  "...",
              "HtmlBody": "...",
              "TextBody": "...",
              "ReplyTo":  "...",
              "Tag":      "...",
              "MessageStream": "outbound",
            }
        """
        from_str = message["from_email"]
        if message.get("from_name"):
            from_str = f"{message['from_name']} <{message['from_email']}>"

        to_str = message["to"]
        if message.get("to_name"):
            to_str = f"{message['to_name']} <{message['to']}>"

        payload: dict[str, Any] = {
            "From": from_str,
            "To": to_str,
            "Subject": message["subject"],
            "MessageStream": "outbound",
        }

        if message.get("html"):
            payload["HtmlBody"] = message["html"]
        if message.get("text"):
            payload["TextBody"] = message["text"]
        if message.get("reply_to"):
            payload["ReplyTo"] = message["reply_to"]
        if message.get("tags"):
            # Postmark only supports a single Tag string
            payload["Tag"] = str(message["tags"][0])

        return payload

    # ── Response parsing ──────────────────────────────────────

    def _parse_response(self, raw: Any) -> str:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"unexpected response type: {type(raw).__name__}",
            )
        error_code = raw.get("ErrorCode")
        if error_code and error_code != 0:
            msg = raw.get("Message", "unknown error")
            raise AdapterError(
                self.name, f"Postmark error {error_code}: {msg}",
            )
        return str(raw.get("MessageID", "") or "postmark-accepted")
