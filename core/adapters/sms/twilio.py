"""TwilioAdapter — Twilio Programmable Messaging.

Wave 1 extension — SMS is the single most commonly missing
comms channel in Shopify stores (order alerts, shipping
updates, abandoned-cart reminders). Capability.SEND_SMS was
already in the enum; this adapter is the mechanical hand that
dispatches.

Auth: HTTP Basic auth. Twilio's Account SID is the username
and the Auth Token is the password. No OAuth, no tokens to
rotate — just two env vars.

Endpoint used:

  * ``POST /2010-04-01/Accounts/{AccountSid}/Messages.json``
        Sends one message. Accepts ``application/x-www-form-urlencoded``
        only — NOT JSON — so the base class routes this call
        through the form path by setting Content-Type in
        ``_auth_headers``.

Cost: Twilio US A2P pricing is roughly $0.0079 per segment as
of 2024 (origination fees + carrier surcharges vary). The
adapter sets ``cost_per_call = 0.0079`` as the conservative
default; the base multiplies by ``segments`` so multi-segment
messages charge the right amount to the budget advisor.

Reference: https://www.twilio.com/docs/messaging/api/message-resource#create-a-message-resource
"""
from __future__ import annotations

import base64
import math
from typing import Any

from ..config import get_config
from ..errors import AdapterError, AdapterNotConfigured
from ._base import SmsBaseAdapter, _REQUESTS_AVAILABLE


_TWILIO_BASE = "https://api.twilio.com"

# GSM-7 basic set fits 160 chars/segment; with concatenation
# UDH headers drop that to 153. Anything containing a character
# outside GSM-7 uses UCS-2 (70 chars/segment, 67 with UDH).
# We conservatively pick the GSM-7 concatenation number — close
# enough for budget projection, exact billing comes from
# Twilio's callback anyway.
_GSM7_SEGMENT_LEN = 160
_GSM7_CONCAT_LEN = 153


class TwilioAdapter(SmsBaseAdapter):
    name = "twilio"
    base_url = _TWILIO_BASE
    # Twilio is the only SMS adapter today, but pin priority
    # high so future alternatives (MessageBird, Plivo) stay
    # secondary unless an operator explicitly prefers them.
    priority = 80
    cost_per_call = 0.0079

    _from_config_alias = "twilio_from_number"

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        cfg = get_config()
        return (
            bool(cfg.get("twilio_account_sid"))
            and bool(cfg.get("twilio_auth_token"))
            and bool(cfg.get("twilio_from_number"))
        )

    # ── URL / auth ────────────────────────────────────────────

    def _send_url(self) -> str:
        sid = get_config().get("twilio_account_sid")
        if not sid:
            raise AdapterNotConfigured(
                self.name,
                "missing Account SID (set $TWILIO_ACCOUNT_SID)",
            )
        return (
            f"{self.base_url}/2010-04-01/Accounts/{sid}/Messages.json"
        )

    def _auth_headers(self) -> dict[str, str]:
        cfg = get_config()
        sid = cfg.get("twilio_account_sid")
        token = cfg.get("twilio_auth_token")
        if not sid or not token:
            raise AdapterNotConfigured(
                self.name,
                "missing credentials (set $TWILIO_ACCOUNT_SID and "
                "$TWILIO_AUTH_TOKEN)",
            )
        basic = base64.b64encode(
            f"{sid}:{token}".encode("utf-8"),
        ).decode("ascii")
        return {
            "Authorization": f"Basic {basic}",
            # Form-encoded body — see note in _base._http_post.
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

    # ── Payload translation ──────────────────────────────────

    def _build_payload(self, params: dict[str, Any]) -> dict[str, Any]:
        """Twilio expects a form-encoded body::

            To=+15551234567
            From=+15559876543
            Body=Your order has shipped
            MediaUrl=https://... (optional, repeatable)

        ``requests`` serialises a dict[str, str] into form-urlencoded
        automatically when we pass ``data=...``.
        """
        from_number = self._resolve_from_number(params)
        if not from_number:
            raise AdapterNotConfigured(
                self.name,
                "missing 'from_number' (set $TWILIO_FROM_NUMBER or "
                "pass per-call 'from_number')",
            )

        form: dict[str, Any] = {
            "To": params["to"],
            "From": from_number,
            "Body": params["body"],
        }

        media_urls = params.get("media_urls") or []
        if media_urls:
            # Twilio accepts repeated MediaUrl fields. requests
            # handles a list value by emitting repeated keys.
            form["MediaUrl"] = [str(u) for u in media_urls]

        return form

    # ── Response parsing ──────────────────────────────────────

    def _parse_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"sms response not a dict: {type(raw).__name__}",
            )

        # Twilio returns ``num_segments`` as a string ("1").
        try:
            segments_raw = raw.get("num_segments")
            segments = int(segments_raw) if segments_raw else (
                self._estimate_segments(params.get("body", ""))
            )
        except (TypeError, ValueError):
            segments = self._estimate_segments(params.get("body", ""))

        return {
            "message_id": str(raw.get("sid", "") or ""),
            "to": str(raw.get("to", "") or params.get("to", "")),
            "status": str(raw.get("status", "") or ""),
            "segments": segments,
        }

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _estimate_segments(body: str) -> int:
        """Conservative segment count when Twilio's response
        doesn't include one. Assumes GSM-7 encoding."""
        if not body:
            return 1
        length = len(body)
        if length <= _GSM7_SEGMENT_LEN:
            return 1
        return int(math.ceil(length / _GSM7_CONCAT_LEN))
