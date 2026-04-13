"""StripeAdapter — Stripe Payments API.

Wave 1 surface — refund + capture + list disputes only. The
brain decides WHEN to refund or capture; this adapter is the
mechanical hand that talks to Stripe.

Auth: Static secret key. Stripe uses a simple ``Authorization:
Bearer sk_...`` header — no OAuth dance, no token refresh.

Environment selection:

  * ``STRIPE_SECRET_KEY=sk_live_...`` → live mode (real money)
  * ``STRIPE_SECRET_KEY=sk_test_...`` → test mode (safe)

Stripe detects live vs test automatically from the key prefix,
so there is no separate ``STRIPE_ENV`` setting — the key itself
encodes the environment.

Endpoints used:

  * ``POST /v1/refunds``
        Create a refund. ``transaction_id`` in the normalised
        params maps to Stripe's ``charge`` or ``payment_intent``
        id.
  * ``POST /v1/charges/{charge_id}/capture``
        Capture an uncaptured charge.
  * ``GET  /v1/disputes``
        List disputes (paginated).

Important: Stripe expects amounts in the **smallest currency
unit** (cents for USD, yen for JPY). The normalised params use
decimal strings ("12.34"), so we convert to cents here.

Reference: https://docs.stripe.com/api
"""
from __future__ import annotations

import math
from typing import Any

from utils.logger import get_logger

from ..config import get_config
from ..errors import AdapterError
from ._base import PaymentBaseAdapter, _REQUESTS_AVAILABLE

logger = get_logger("adapters.payment.stripe")

_BASE_URL = "https://api.stripe.com"

# Stripe API version header — pin so response shapes don't shift
# when Stripe pushes a new default version. Operators can override
# via STRIPE_API_VERSION env var.
_DEFAULT_API_VERSION = "2024-12-18.acacia"

# Zero-decimal currencies where 1 unit = 1 of the real currency
# (JPY, KRW, etc.). For these, the normalised decimal amount
# passes through unchanged as an integer.
_ZERO_DECIMAL_CURRENCIES = frozenset({
    "BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA",
    "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
})


def _amount_to_cents(amount_str: str, currency: str) -> int:
    """Convert a decimal string amount to Stripe's smallest-unit
    integer. ``"12.34"`` + ``"USD"`` → ``1234``.

    Zero-decimal currencies (JPY, KRW, etc.) skip multiplication.
    """
    value = float(amount_str)
    if currency.upper() in _ZERO_DECIMAL_CURRENCIES:
        return int(math.floor(value))
    return int(round(value * 100))


class StripeAdapter(PaymentBaseAdapter):
    name = "stripe"
    # Lower priority than PayPal (80) so if both are configured,
    # PayPal wins by default — the store's existing gateway should
    # be the primary handler. Operators can override via
    # ActionWeightStore if they prefer Stripe.
    priority = 70
    cost_per_call = 0.0

    base_url: str = _BASE_URL

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        return bool(get_config().get("stripe_secret_key"))

    def is_live(self) -> bool:
        """True iff the secret key is a live key (``sk_live_...``)."""
        key = get_config().get("stripe_secret_key") or ""
        return key.startswith("sk_live_")

    # ── Auth ───────────────────────────────────────────────────

    def _bearer_token(self) -> str:
        """Stripe uses the secret key directly as the bearer token."""
        return get_config().get("stripe_secret_key") or ""

    def _auth_headers(self) -> dict[str, str]:
        api_version = (
            get_config().get("stripe_api_version")
            or _DEFAULT_API_VERSION
        )
        return {
            "Authorization": f"Bearer {self._bearer_token()}",
            "Stripe-Version": api_version,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

    # ── URL builders ───────────────────────────────────────────

    def _refund_url(self, transaction_id: str) -> str:
        # Stripe v1/refunds accepts `charge` or `payment_intent`
        # as a body param, so the URL is always the same.
        return f"{self.base_url}/v1/refunds"

    def _capture_url(self, authorization_id: str) -> str:
        return (
            f"{self.base_url}/v1/charges/{authorization_id}/capture"
        )

    def _disputes_url(self, params: dict[str, Any]) -> str:
        query: list[str] = []
        page_size = params.get("page_size")
        try:
            limit = int(page_size) if page_size is not None else 20
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(100, limit))
        query.append(f"limit={limit}")

        status = params.get("status")
        if status:
            # Stripe uses lowercase status values
            query.append(f"status={str(status).lower()}")
        created_after = params.get("created_after")
        if created_after:
            # Stripe uses unix timestamps for created[gte]
            import datetime as _dt
            try:
                ts = int(
                    _dt.datetime.fromisoformat(
                        created_after.replace("Z", "+00:00"),
                    ).timestamp()
                )
                query.append(f"created[gte]={ts}")
            except (ValueError, AttributeError) as exc:
                _ = exc  # skip bad date filter; keep wave11 clean

        return f"{self.base_url}/v1/disputes?" + "&".join(query)

    # ── Payload builders ───────────────────────────────────────

    def _build_refund_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        """Stripe ``POST /v1/refunds`` expects form-encoded params.

        The ``_http_request`` in the base sends JSON, but Stripe's
        refund endpoint accepts the ``charge`` / ``payment_intent``
        and ``amount`` as top-level keys. The base class's
        ``_http_post`` sends these as JSON, which Stripe's API also
        accepts when Content-Type is set correctly.

        However, Stripe prefers form encoding. We override
        ``_do_refund`` below to use form-encoded POST.
        """
        body: dict[str, Any] = {}
        tx_id = params["transaction_id"]
        # Detect if it's a PaymentIntent or a Charge
        if tx_id.startswith("pi_"):
            body["payment_intent"] = tx_id
        else:
            body["charge"] = tx_id

        amount = params.get("amount")
        if amount is not None:
            currency = str(params["currency"]).upper()
            body["amount"] = _amount_to_cents(str(amount), currency)
            body["currency"] = currency.lower()

        reason = params.get("reason")
        if reason:
            # Stripe accepts: duplicate, fraudulent, requested_by_customer
            body["reason"] = str(reason)

        metadata = params.get("metadata") or {}
        if metadata:
            for k, v in metadata.items():
                body[f"metadata[{k}]"] = str(v)

        return body

    def _build_capture_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        amount = params.get("amount")
        if amount is not None:
            currency = str(params["currency"]).upper()
            body["amount"] = _amount_to_cents(str(amount), currency)
        return body

    # ── Override HTTP for Stripe form encoding ─────────────────

    def _do_refund(self, params: dict[str, Any]) -> AdapterResult:
        """Override base refund to use form-encoded POST."""
        from ..base import AdapterResult, Capability

        self._validate_refund(params)
        url = self._refund_url(params["transaction_id"])
        body = self._build_refund_payload(params)
        raw = self._stripe_form_post(url, body)
        normalised = self._parse_refund_response(raw, params)
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.PAYMENT_REFUND.value,
            data=normalised,
            raw=raw,
        )

    def _do_capture(self, params: dict[str, Any]) -> AdapterResult:
        """Override base capture to use form-encoded POST."""
        from ..base import AdapterResult, Capability

        self._validate_capture(params)
        url = self._capture_url(params["authorization_id"])
        body = self._build_capture_payload(params)
        raw = self._stripe_form_post(url, body)
        normalised = self._parse_capture_response(raw, params)
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.PAYMENT_CAPTURE.value,
            data=normalised,
            raw=raw,
        )

    def _stripe_form_post(
        self, url: str, data: dict[str, Any],
    ) -> Any:
        """POST with ``application/x-www-form-urlencoded`` body,
        which is what Stripe prefers for most endpoints."""
        from ..errors import (
            AdapterAuthError,
            AdapterError,
            AdapterRateLimited,
            AdapterTimeout,
            AdapterUnavailable,
        )

        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )

        headers = self._auth_headers()
        try:
            import requests as _req
            response = _req.post(
                url, data=data, headers=headers,
                timeout=self.timeout,
            )
        except Exception as exc:
            # Re-use the base class's error classification logic
            # by checking the exception type name.
            exc_name = type(exc).__name__
            if "Timeout" in exc_name:
                raise AdapterTimeout(
                    self.name, f"timeout after {self.timeout}s: {exc}",
                ) from exc
            if "ConnectionError" in exc_name:
                raise AdapterUnavailable(
                    self.name, f"connection error: {exc}",
                ) from exc
            raise AdapterError(
                self.name, f"http post failed: {exc_name}: {exc}",
            ) from exc

        status = getattr(response, "status_code", 0)
        if status >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if status in (401, 403):
                raise AdapterAuthError(
                    self.name,
                    f"Stripe rejected credentials ({status}): {snippet}",
                )
            if status == 429:
                raise AdapterRateLimited(
                    self.name, f"rate limit (429): {snippet}",
                )
            if 500 <= status < 600:
                raise AdapterUnavailable(
                    self.name, f"Stripe 5xx ({status}): {snippet}",
                )
            raise AdapterError(
                self.name, f"Stripe returned {status}: {snippet}",
            )

        try:
            text = getattr(response, "text", "") or ""
            return response.json() if text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON response: {exc}",
            ) from exc

    # ── Response parsers ───────────────────────────────────────

    def _parse_refund_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"refund response not a dict: {type(raw).__name__}",
            )
        # Stripe returns amount in cents — convert back to decimal
        amount_cents = raw.get("amount", 0)
        currency = str(raw.get("currency", "") or "").upper()
        if currency in _ZERO_DECIMAL_CURRENCIES:
            amount_str = str(amount_cents)
        else:
            amount_str = f"{int(amount_cents) / 100:.2f}"

        return {
            "refund_id": str(raw.get("id", "") or ""),
            "status": str(raw.get("status", "") or "").upper(),
            "amount": amount_str,
            "currency": currency,
            "transaction_id": params["transaction_id"],
        }

    def _parse_capture_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"capture response not a dict: {type(raw).__name__}",
            )
        amount_cents = raw.get("amount_captured", raw.get("amount", 0))
        currency = str(raw.get("currency", "") or "").upper()
        if currency in _ZERO_DECIMAL_CURRENCIES:
            amount_str = str(amount_cents)
        else:
            amount_str = f"{int(amount_cents) / 100:.2f}"

        return {
            "capture_id": str(raw.get("id", "") or ""),
            "status": str(raw.get("status", "") or "").upper(),
            "amount": amount_str,
            "currency": currency,
            "authorization_id": params["authorization_id"],
        }

    def _parse_disputes_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"disputes response not a dict: {type(raw).__name__}",
            )
        items = raw.get("data") or []
        normalised: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            amount_cents = item.get("amount", 0)
            currency = str(item.get("currency", "") or "").upper()
            if currency in _ZERO_DECIMAL_CURRENCIES:
                amount_str = str(amount_cents)
            else:
                amount_str = f"{int(amount_cents) / 100:.2f}"
            normalised.append({
                "dispute_id": str(item.get("id", "") or ""),
                "status": str(item.get("status", "") or ""),
                "reason": str(item.get("reason", "") or ""),
                "amount": amount_str,
                "currency": currency,
            })
        return {
            "disputes": normalised,
            "count": len(normalised),
        }
