"""SmsBaseAdapter — shared HTTP base for SMS adapters.

Concrete adapters (Twilio today; MessageBird, Vonage, Plivo
later) inherit this class and override only the vendor-specific
bits:

  * ``base_url``               — vendor API root
  * ``_send_url``              — endpoint that dispatches a
                                  message
  * ``_auth_headers``          — vendor-specific auth header
  * ``_build_payload``         — Message → vendor body
  * ``_parse_response``        — vendor response → normalised
                                  dict

The base handles:

  * Capability dispatch for ``Capability.SEND_SMS``
  * Required-field validation (``to``, ``body``; optional
    ``from_number`` override)
  * E.164 shape check on phone numbers
  * HTTP POST execution with typed error mapping
  * AdapterResult assembly

Normalised request shape (vendor-agnostic):

    {
        "to":          "+15551234567",     # required, E.164
        "body":        "Your order ...",   # required (max 1600)
        "from_number": "+15559876543",     # optional override
        "media_urls":  ["https://..."],    # optional MMS
        "metadata":    {"order_id": "1"},  # optional tags
    }

Normalised response shape:

    {
        "message_id": "SM1234...",
        "to":         "+15551234567",
        "status":     "queued",
        "segments":   1,
    }

Scope note: Wave 1 covers *send* only. Webhook delivery
callbacks, two-way conversations, message templates, and
phone-number provisioning are out of scope — they belong in a
later wave once the one-way send path is proven in production.
"""
from __future__ import annotations

import re
from typing import Any

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = get_logger("adapters.sms")


_DEFAULT_TIMEOUT = 15.0

# E.164: leading "+" followed by 8–15 digits. Deliberately
# permissive — we reject obvious garbage (letters, too-short
# strings) but trust the vendor to reject numbers with invalid
# country codes or unreachable destinations.
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")

# SMS segment boundary. 160 GSM-7 chars per segment, but with
# concatenation the vendor will split automatically up to ~10
# segments (~1600 chars). We reject anything longer so callers
# don't accidentally send a novel and see a cryptic vendor
# error.
_MAX_BODY_LEN = 1600


class SmsBaseAdapter(BaseAdapter):
    """Abstract base for every SMS adapter.

    Concrete adapters MUST set:

      * ``name``       — registry key (e.g. ``"twilio"``)
      * ``base_url``   — vendor API root

    They MAY override:

      * ``priority``      — router preference (0-100)
      * ``cost_per_call`` — average $/message (Twilio US is
                            ~$0.0079 as of 2024)
      * ``timeout``       — per-request timeout in seconds
    """

    category = AdapterCategory.SMS
    capabilities = {Capability.SEND_SMS}

    base_url: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    priority: int = 50

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        """Sub-classes override to check the vendor's credential
        set. Default returns False so an unconfigured base class
        never accidentally satisfies the router."""
        return False

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability != Capability.SEND_SMS:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        self._validate_message(params)
        url = self._send_url()
        body = self._build_payload(params)
        raw = self._http_post(url, body, headers=self._auth_headers())
        normalised = self._parse_response(raw, params)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data=normalised,
            cost_usd=float(self.cost_per_call) * int(
                normalised.get("segments", 1) or 1,
            ),
            raw=raw,
        )

    # ── Validation ─────────────────────────────────────────────

    def _validate_message(self, params: dict[str, Any]) -> None:
        to = params.get("to")
        if not to or not isinstance(to, str):
            raise AdapterValidationError(
                self.name, "'to' is required for SMS send",
            )
        if not _E164.match(to):
            raise AdapterValidationError(
                self.name,
                f"'to' must be E.164 (e.g. +15551234567), got {to!r}",
            )

        body = params.get("body")
        if not body or not isinstance(body, str):
            raise AdapterValidationError(
                self.name, "'body' is required and must be a string",
            )
        if len(body) > _MAX_BODY_LEN:
            raise AdapterValidationError(
                self.name,
                f"'body' too long ({len(body)} chars; max {_MAX_BODY_LEN})",
            )

        from_number = params.get("from_number")
        if from_number is not None:
            if not isinstance(from_number, str) or not _E164.match(from_number):
                raise AdapterValidationError(
                    self.name,
                    f"'from_number' must be E.164, got {from_number!r}",
                )

    # ── Vendor-specific hooks (override in subclasses) ────────

    def _send_url(self) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}._send_url must be implemented",
        )

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token. Override when the vendor uses
        Basic auth (Twilio) or a custom scheme."""
        raise NotImplementedError(
            f"{type(self).__name__}._auth_headers must be implemented",
        )

    def _build_payload(self, params: dict[str, Any]) -> Any:
        raise NotImplementedError(
            f"{type(self).__name__}._build_payload must be implemented",
        )

    def _parse_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._parse_response must be implemented",
        )

    def _resolve_from_number(self, params: dict[str, Any]) -> str:
        """Pick the sender: per-call override first, then the
        tenant default from config."""
        override = params.get("from_number")
        if override:
            return str(override)
        return get_config().get(self._from_config_alias)

    # Subclasses override to point at their config alias for the
    # tenant-wide "from" number.
    _from_config_alias: str = ""

    # ── HTTP ───────────────────────────────────────────────────

    def _http_post(
        self,
        url: str,
        body: Any,
        headers: dict[str, str],
    ) -> Any:
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        try:
            # Twilio uses form-encoded, not JSON. We detect that
            # from the Content-Type header the subclass set.
            if headers.get("Content-Type") == "application/x-www-form-urlencoded":
                response = _requests.post(
                    url, data=body, headers=headers, timeout=self.timeout,
                )
            else:
                response = _requests.post(
                    url, json=body, headers=headers, timeout=self.timeout,
                )
        except _requests.Timeout as exc:  # type: ignore[union-attr]
            raise AdapterTimeout(
                self.name, f"timeout after {self.timeout}s: {exc}",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            raise AdapterUnavailable(
                self.name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"http post failed: {type(exc).__name__}: {exc}",
            ) from exc

        status = getattr(response, "status_code", 0)
        if status >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if status in (401, 403):
                raise AdapterAuthError(
                    self.name,
                    f"vendor rejected credentials ({status}): {snippet}",
                )
            if status == 429:
                raise AdapterRateLimited(
                    self.name, f"rate limit (429): {snippet}",
                )
            if 500 <= status < 600:
                raise AdapterUnavailable(
                    self.name,
                    f"vendor 5xx ({status}): {snippet}",
                )
            raise AdapterError(
                self.name,
                f"vendor returned {status}: {snippet}",
            )

        try:
            text = getattr(response, "text", "") or ""
            return response.json() if text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON response: {exc}",
            ) from exc
