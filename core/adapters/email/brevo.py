"""BrevoAdapter — Brevo (Sendinblue) transactional email.

Why Brevo is the primary email adapter:

  * **9,000 emails/month forever free** (300/day) — the most
    generous unconditional free tier among transactional email
    vendors. Resend's 3,000/month and SendGrid's gone-as-of-2025
    can't match it.
  * **Unlimited contacts** — no quota on how many recipients
    the adapter can target, only on emails/day.
  * **Single REST endpoint** — ``POST /v3/smtp/email`` takes a
    compact JSON body and returns the message id. No SDK, no
    SMTP setup, no tenant config.

Auth: custom ``api-key`` header (NOT ``Authorization: Bearer``).
Brevo accepts the raw API key value — no token scheme prefix.

Reference: https://developers.brevo.com/reference/sendtransacemail
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import EmailBaseAdapter


class BrevoAdapter(EmailBaseAdapter):
    name = "brevo"
    base_url = "https://api.brevo.com/v3"
    config_alias = "brevo"

    # Highest email priority — 9K/mo free beats Resend's 3K/mo
    # for the default case. Router picks Brevo whenever it's
    # configured.
    priority = 90
    cost_per_call = 0.0
    free_tier_daily_limit = 300
    free_tier_monthly_limit = 9_000

    # ── URL / auth hooks ──────────────────────────────────────

    def _send_url(self) -> str:
        return f"{self.base_url}/smtp/email"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "api-key": self._api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Payload translation ──────────────────────────────────

    def _build_payload(self, message: dict[str, Any]) -> dict[str, Any]:
        """Brevo expects:

            {
              "sender": {"name": "...", "email": "..."},
              "to":     [{"email": "...", "name": "..."}],
              "subject": "...",
              "htmlContent": "...",
              "textContent": "...",
              "replyTo": {"email": "..."},    # optional
              "tags":    [...],                # optional
            }
        """
        sender: dict[str, Any] = {"email": message["from_email"]}
        if message.get("from_name"):
            sender["name"] = message["from_name"]

        to_entry: dict[str, Any] = {"email": message["to"]}
        if message.get("to_name"):
            to_entry["name"] = message["to_name"]

        payload: dict[str, Any] = {
            "sender": sender,
            "to": [to_entry],
            "subject": message["subject"],
        }

        if message.get("html"):
            payload["htmlContent"] = message["html"]
        if message.get("text"):
            payload["textContent"] = message["text"]
        if message.get("reply_to"):
            payload["replyTo"] = {"email": message["reply_to"]}
        if message.get("tags"):
            payload["tags"] = list(message["tags"])

        return payload

    # ── Response parsing ──────────────────────────────────────

    def _parse_response(self, raw: Any) -> str:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"unexpected response type: {type(raw).__name__}",
            )
        return str(raw.get("messageId", "") or "")
