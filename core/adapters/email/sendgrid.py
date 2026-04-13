"""SendGridAdapter — SendGrid (Twilio) transactional email.

SendGrid adds a third email provider to the router's fallback
chain. When Brevo (primary, priority 90) or Resend (secondary,
75) are down or throttled, the router cascades to SendGrid
automatically.

Strengths:

  * **100 emails/day forever free** — smaller quota than Brevo
    but enough for a backup path.
  * **Best-in-class deliverability** — Twilio's infrastructure
    handles billions of emails; shared IPs have strong Gmail/
    Outlook reputation.
  * **Standard Bearer auth** — ``Authorization: Bearer {key}``.

Why it's third priority:

  * Free tier is the smallest (100/day ≈ 3,000/month).
  * The v3 mail send endpoint is more verbose than Brevo/Resend
    (nested ``personalizations`` array). The adapter translates
    the normalised ``EmailMessage`` transparently.

Reference: https://docs.sendgrid.com/api-reference/mail-send/mail-send
"""
from __future__ import annotations

from typing import Any

from ..errors import AdapterError
from ._base import EmailBaseAdapter


class SendGridAdapter(EmailBaseAdapter):
    name = "sendgrid"
    base_url = "https://api.sendgrid.com/v3"
    config_alias = "sendgrid"

    # Lowest email priority — smallest free tier. Router picks
    # Brevo (90) or Resend (75) first. SendGrid is the safety
    # net when neither is available.
    priority = 60
    cost_per_call = 0.0
    free_tier_daily_limit = 100
    free_tier_monthly_limit = 3_000

    # ── URL / auth hooks ──────────────────────────────────────

    def _send_url(self) -> str:
        return f"{self.base_url}/mail/send"

    # ``_auth_headers`` inherits the base default (Bearer token)

    # ── Payload translation ──────────────────────────────────

    def _build_payload(self, message: dict[str, Any]) -> dict[str, Any]:
        """SendGrid v3 mail/send expects:

            {
              "personalizations": [{"to": [{"email": "...", "name": "..."}]}],
              "from":    {"email": "...", "name": "..."},
              "subject": "...",
              "content": [
                  {"type": "text/plain", "value": "..."},
                  {"type": "text/html",  "value": "..."},
              ],
              "reply_to":    {"email": "..."},       # optional
              "categories":  ["tag1", "tag2"],        # optional
            }
        """
        # Personalizations (recipients)
        to_entry: dict[str, Any] = {"email": message["to"]}
        if message.get("to_name"):
            to_entry["name"] = message["to_name"]

        personalizations = [{"to": [to_entry]}]

        # Sender
        from_entry: dict[str, Any] = {"email": message["from_email"]}
        if message.get("from_name"):
            from_entry["name"] = message["from_name"]

        payload: dict[str, Any] = {
            "personalizations": personalizations,
            "from": from_entry,
            "subject": message["subject"],
        }

        # Content — SendGrid requires at least one content block
        content: list[dict[str, str]] = []
        if message.get("text"):
            content.append({"type": "text/plain", "value": message["text"]})
        if message.get("html"):
            content.append({"type": "text/html", "value": message["html"]})
        payload["content"] = content

        # Optional fields
        if message.get("reply_to"):
            payload["reply_to"] = {"email": message["reply_to"]}
        if message.get("tags"):
            payload["categories"] = [str(t) for t in message["tags"]]

        return payload

    # ── Response parsing ──────────────────────────────────────

    def _parse_response(self, raw: Any) -> str:
        """SendGrid's ``POST /v3/mail/send`` returns 202 Accepted
        with an empty body on success. The message id comes back
        in the ``X-Message-Id`` response header, which the base
        class's ``_http_post`` doesn't capture.

        When the raw response is empty (``{}``) we return a
        placeholder id. When SendGrid returns an error body, it's
        a dict with ``errors`` key — we extract the first message.
        """
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"unexpected response type: {type(raw).__name__}",
            )
        # SendGrid returns empty body on 202 success
        if not raw:
            return "sendgrid-accepted"
        # Error responses have {"errors": [{"message": "..."}]}
        errors = raw.get("errors")
        if errors and isinstance(errors, list):
            first_msg = errors[0].get("message", "") if errors else ""
            raise AdapterError(self.name, f"SendGrid error: {first_msg}")
        return str(raw.get("id", "") or "sendgrid-accepted")
