"""KlaviyoAdapter — Klaviyo email & SMS marketing.

Klaviyo is the dominant email/SMS marketing platform in the
Shopify ecosystem. Unlike transactional-only senders (Resend,
SendGrid), Klaviyo excels at:

  * **Flows** — automated sequences (abandoned cart, welcome,
    win-back) triggered by Shopify events
  * **Campaigns** — one-time sends to segments
  * **Transactional** — order confirmations, shipping updates
  * **SMS** — text message marketing (US/CA/UK/AU)

The adapter wraps Klaviyo's v2024-10-15 revision API and exposes
both ``SEND_EMAIL_TRANSACTIONAL`` and ``SEND_EMAIL_CAMPAIGN``
through the standard ``EmailBaseAdapter`` contract.

Free tier: 500 email sends/month, 150 SMS credits.
Pricing: from $20/month for 500 contacts.

Reference: https://developers.klaviyo.com/en/reference/api_overview
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import EmailBaseAdapter


_KLAVIYO_REVISION = "2024-10-15"


class KlaviyoAdapter(EmailBaseAdapter):
    name = "klaviyo"
    base_url = "https://a.klaviyo.com/api"
    config_alias = "klaviyo"

    # High priority — Klaviyo is the primary marketing email
    # platform for Shopify stores. Router picks it first for
    # campaigns, falls back to Brevo/Resend for transactional.
    priority = 95
    cost_per_call = 0.0
    free_tier_daily_limit = 0
    free_tier_monthly_limit = 500

    # ── URL / auth hooks ──────────────────────────────────────

    def _send_url(self) -> str:
        return f"{self.base_url}/events"

    def _auth_headers(self) -> dict[str, str]:
        """Klaviyo uses a private API key in the ``Authorization``
        header with ``Klaviyo-API-Key`` prefix (NOT Bearer)."""
        return {
            "Authorization": f"Klaviyo-API-Key {self._api_key()}",
            "revision": _KLAVIYO_REVISION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Payload translation ──────────────────────────────────

    def _build_payload(self, message: dict[str, Any]) -> dict[str, Any]:
        """Klaviyo's event-based send model:

        For transactional email, we create an event that triggers
        a Klaviyo flow. The event carries the email data as
        properties, and a preconfigured flow template renders it.

        Payload shape (Klaviyo Events API)::

            {
              "data": {
                "type": "event",
                "attributes": {
                  "metric": {"data": {"type": "metric", "attributes": {"name": "..."}}},
                  "profile": {"data": {"type": "profile", "attributes": {"email": "..."}}},
                  "properties": {
                    "subject": "...",
                    "html": "...",
                    "text": "..."
                  }
                }
              }
            }
        """
        # Profile (recipient)
        profile_attrs: dict[str, Any] = {"email": message["to"]}
        if message.get("to_name"):
            # Split first/last name if space present
            parts = message["to_name"].split(" ", 1)
            profile_attrs["first_name"] = parts[0]
            if len(parts) > 1:
                profile_attrs["last_name"] = parts[1]

        # Event properties carry the email content
        properties: dict[str, Any] = {
            "subject": message["subject"],
            "from_email": message["from_email"],
        }
        if message.get("from_name"):
            properties["from_name"] = message["from_name"]
        if message.get("html"):
            properties["html"] = message["html"]
        if message.get("text"):
            properties["text"] = message["text"]
        if message.get("reply_to"):
            properties["reply_to"] = message["reply_to"]
        if message.get("tags"):
            properties["tags"] = message["tags"]

        # Determine metric name from capability context
        metric_name = "ShopAI Transactional Email"
        if message.get("tags") and any(
            "campaign" in str(t).lower() for t in message["tags"]
        ):
            metric_name = "ShopAI Campaign Email"

        return {
            "data": {
                "type": "event",
                "attributes": {
                    "metric": {
                        "data": {
                            "type": "metric",
                            "attributes": {"name": metric_name},
                        },
                    },
                    "profile": {
                        "data": {
                            "type": "profile",
                            "attributes": profile_attrs,
                        },
                    },
                    "properties": properties,
                },
            },
        }

    # ── Response parsing ──────────────────────────────────────

    def _parse_response(self, raw: Any) -> str:
        """Klaviyo Events API returns empty body on 202 success.
        Error responses have ``{"errors": [{"detail": "..."}]}``."""
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"unexpected response type: {type(raw).__name__}",
            )
        # Empty body = success
        if not raw:
            return "klaviyo-accepted"

        # Error responses
        errors = raw.get("errors")
        if errors and isinstance(errors, list):
            detail = errors[0].get("detail", "") if errors else ""
            raise AdapterError(self.name, f"Klaviyo error: {detail}")

        return str(raw.get("id", "") or "klaviyo-accepted")
