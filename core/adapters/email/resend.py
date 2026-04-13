"""ResendAdapter — Resend modern transactional email.

Resend sits in the router chain as a secondary email adapter.
Strengths over Brevo:

  * **Modern developer API** — clean REST, great docs, React
    Email template support (when the caller supplies React-
    rendered HTML).
  * **Simple auth** — standard ``Authorization: Bearer`` header.
  * **Best-in-class free tier deliverability** — Resend's
    shared IPs have a good reputation with Gmail/Outlook.

Why it's secondary:

  * **3,000 emails/month** on the free tier, vs Brevo's 9,000.
    The router prefers Brevo when both are configured unless
    the caller explicitly opts in with ``RouteContext(prefer=
    ["resend"])``.

Reference: https://resend.com/docs/api-reference/emails/send-email
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import EmailBaseAdapter


class ResendAdapter(EmailBaseAdapter):
    name = "resend"
    base_url = "https://api.resend.com"
    config_alias = "resend"

    # Lower priority than Brevo (90) — Resend's free tier is
    # smaller, so router picks Brevo by default. Still high
    # enough that the router prefers it over unconfigured
    # alternatives.
    priority = 75
    cost_per_call = 0.0
    free_tier_daily_limit = 100
    free_tier_monthly_limit = 3_000

    # ── URL / auth hooks ──────────────────────────────────────

    def _send_url(self) -> str:
        return f"{self.base_url}/emails"

    # ``_auth_headers`` inherits the base default (Bearer token)

    # ── Payload translation ──────────────────────────────────

    def _build_payload(self, message: dict[str, Any]) -> dict[str, Any]:
        """Resend expects:

            {
              "from":    "Name <email@example.com>" OR "email@example.com",
              "to":      ["email@example.com"],
              "subject": "...",
              "html":    "...",
              "text":    "...",
              "reply_to":"...",    # optional
              "tags":    [{"name": "...", "value": "..."}],  # optional
            }
        """
        from_value: str = message["from_email"]
        if message.get("from_name"):
            from_value = f"{message['from_name']} <{message['from_email']}>"

        payload: dict[str, Any] = {
            "from": from_value,
            "to": [message["to"]],
            "subject": message["subject"],
        }

        if message.get("html"):
            payload["html"] = message["html"]
        if message.get("text"):
            payload["text"] = message["text"]
        if message.get("reply_to"):
            payload["reply_to"] = message["reply_to"]

        # Resend wants tags as [{"name": ..., "value": ...}]
        # rather than plain strings. Convert transparently so
        # callers use the same shape across vendors.
        if message.get("tags"):
            payload["tags"] = [
                {"name": "category", "value": str(t)}
                for t in message["tags"]
            ]

        return payload

    # ── Response parsing ──────────────────────────────────────

    def _parse_response(self, raw: Any) -> str:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"unexpected response type: {type(raw).__name__}",
            )
        return str(raw.get("id", "") or "")
