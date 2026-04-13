"""MessageBirdAdapter — MessageBird (now Bird) SMS messaging.

MessageBird is a global cloud communications platform with
excellent coverage in Europe and Asia-Pacific. Acts as Twilio's
fallback for SMS delivery.

Auth: ``Authorization: AccessKey {key}`` header.
Free tier: None (pay-per-message, ~$0.006/SMS US).
Pricing: per-message, varies by country.

Reference: https://developers.messagebird.com/api/sms-messaging/
"""
from __future__ import annotations

from typing import Any

from ..config import get_config
from ..errors import AdapterError, AdapterNotConfigured
from ._base import SmsBaseAdapter, _REQUESTS_AVAILABLE


class MessageBirdAdapter(SmsBaseAdapter):
    name = "messagebird"
    base_url = "https://rest.messagebird.com"

    priority = 60  # Below Twilio (80)
    cost_per_call = 0.006

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        return bool(get_config().get("messagebird"))

    # ── URL / auth ────────────────────────────────────────────

    def _send_url(self) -> str:
        return f"{self.base_url}/messages"

    def _auth_headers(self) -> dict[str, str]:
        key = get_config().get("messagebird")
        if not key:
            raise AdapterNotConfigured(
                self.name,
                "missing API key (set $MESSAGEBIRD_API_KEY)",
            )
        return {
            "Authorization": f"AccessKey {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Payload translation ──────────────────────────────────

    def _build_payload(self, params: dict[str, Any]) -> dict[str, Any]:
        """MessageBird expects JSON::

            {
              "originator": "ShopAI",
              "recipients": ["+15551234567"],
              "body": "Your order..."
            }
        """
        originator = params.get("from_number") or "ShopAI"
        # MessageBird accepts alphanumeric originators (max 11 chars)
        # or E.164 phone numbers
        if originator.startswith("+"):
            pass  # E.164 phone number
        elif len(originator) > 11:
            originator = originator[:11]

        return {
            "originator": originator,
            "recipients": [params["to"]],
            "body": params["body"],
        }

    # ── Response parsing ──────────────────────────────────────

    def _parse_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"sms response not a dict: {type(raw).__name__}",
            )

        # MessageBird returns errors in {"errors": [{"description": "..."}]}
        errors = raw.get("errors")
        if errors and isinstance(errors, list):
            msg = errors[0].get("description", "unknown error")
            raise AdapterError(self.name, f"MessageBird error: {msg}")

        # Parse recipients for segment count
        recipients = raw.get("recipients", {})
        total_count = recipients.get("totalCount", 1) if isinstance(recipients, dict) else 1

        return {
            "message_id": str(raw.get("id", "") or ""),
            "to": params.get("to", ""),
            "status": str(
                raw.get("recipients", {}).get("items", [{}])[0].get("status", "sent")
                if isinstance(raw.get("recipients"), dict)
                else "sent"
            ),
            "segments": total_count,
        }
