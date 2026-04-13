"""PayPalAdapter — PayPal REST v2 (Orders + Disputes).

Wave 1 surface — refund + capture + list disputes only. The
brain decides WHEN to refund or capture; this adapter is the
mechanical hand that talks to PayPal.

Auth: OAuth2 client credentials. The adapter exchanges the
client id + client secret for a short-lived bearer token via
``POST /v1/oauth2/token`` and caches it until ~60 seconds before
expiry. Token fetches are guarded by a thread lock so concurrent
calls do not stampede the auth endpoint.

Environment selection:

  * ``PAYPAL_ENV=live``    → ``https://api-m.paypal.com``
  * ``PAYPAL_ENV=sandbox`` → ``https://api-m.sandbox.paypal.com``
                              (default — anything other than the
                              literal ``"live"`` is treated as
                              sandbox so a misconfigured env var
                              never accidentally hits real money)

Endpoints used:

  * ``POST /v1/oauth2/token``
        OAuth2 token exchange.
  * ``POST /v2/payments/captures/{capture_id}/refund``
        Refund a captured payment. ``transaction_id`` in the
        normalised refund params maps to PayPal's capture id.
  * ``POST /v2/payments/authorizations/{auth_id}/capture``
        Capture an authorisation.
  * ``GET  /v1/customer/disputes``
        List disputes (paginated).

Reference: https://developer.paypal.com/api/rest/

Why PayPal first (instead of Stripe):

* The store owner already has PayPal connected to the Shopify
  storefront, so refunds against existing PayPal transactions
  are immediately useful — no separate vendor signup, no test
  cards, no webhook plumbing.
* OAuth2 client credentials is a more interesting auth pattern
  than Stripe's static secret key, and exercising it here means
  the next OAuth-based adapter (Klaviyo, HubSpot, etc.) can
  copy the token-cache pattern verbatim.
"""
from __future__ import annotations

import base64
import threading
import time
from typing import Any

from utils.logger import get_logger

from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
)
from ._base import PaymentBaseAdapter, _REQUESTS_AVAILABLE, _requests

logger = get_logger("adapters.payment.paypal")


_LIVE_BASE_URL = "https://api-m.paypal.com"
_SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"

# Refresh the OAuth token this many seconds before its declared
# ``expires_in`` so an in-flight call never trips on an expired
# bearer header.
_TOKEN_REFRESH_LEAD_SECONDS = 60.0


class PayPalAdapter(PaymentBaseAdapter):
    name = "paypal"
    # Higher than the base default (50) so PayPal wins routing
    # ties when an operator wires a second processor later — the
    # already-connected store gateway should be the default
    # choice for refunds and captures.
    priority = 80
    cost_per_call = 0.0

    def __init__(self) -> None:
        super().__init__()
        self._token_lock = threading.Lock()
        self._cached_token: str = ""
        self._token_expires_at: float = 0.0

    # ── Configuration ──────────────────────────────────────────

    @property
    def base_url(self) -> str:
        env = (get_config().get("paypal_env") or "").strip().lower()
        return _LIVE_BASE_URL if env == "live" else _SANDBOX_BASE_URL

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        cfg = get_config()
        return bool(cfg.get("paypal_client_id")) and bool(
            cfg.get("paypal_client_secret"),
        )

    def is_live(self) -> bool:
        """True iff the adapter is talking to the live (real
        money) PayPal endpoint. Useful for the JudgmentAdvisor
        guardrail."""
        env = (get_config().get("paypal_env") or "").strip().lower()
        return env == "live"

    # ── OAuth2 token cache ─────────────────────────────────────

    def _bearer_token(self) -> str:
        """Return a valid OAuth2 bearer token, fetching a new one
        only when the cached token is missing or close to expiry.

        Thread-safe: a single token lock serialises refreshes so
        concurrent ``_execute()`` calls do not stampede the auth
        endpoint.
        """
        now = time.monotonic()
        if (
            self._cached_token
            and now < self._token_expires_at - _TOKEN_REFRESH_LEAD_SECONDS
        ):
            return self._cached_token

        with self._token_lock:
            # Re-check after taking the lock — another thread may
            # have already refreshed.
            now = time.monotonic()
            if (
                self._cached_token
                and now < self._token_expires_at - _TOKEN_REFRESH_LEAD_SECONDS
            ):
                return self._cached_token

            token, expires_in = self._fetch_token()
            self._cached_token = token
            # ``time.monotonic`` so the cache survives wall-clock
            # adjustments without spuriously expiring.
            self._token_expires_at = time.monotonic() + max(
                expires_in, 0.0,
            )
            return self._cached_token

    def _fetch_token(self) -> tuple[str, float]:
        """Exchange the configured client id + secret for an OAuth2
        bearer token. Returns ``(access_token, expires_in_seconds)``.

        Lives on the adapter (rather than ``_http_request``) because
        the auth endpoint uses ``application/x-www-form-urlencoded``
        and HTTP Basic auth — neither of which the JSON helpers in
        ``PaymentBaseAdapter`` understand.
        """
        cfg = get_config()
        client_id = cfg.get("paypal_client_id")
        client_secret = cfg.get("paypal_client_secret")
        if not client_id or not client_secret:
            raise AdapterNotConfigured(
                self.name,
                "missing PayPal client credentials "
                "(set $PAYPAL_CLIENT_ID and $PAYPAL_CLIENT_SECRET)",
            )

        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )

        url = f"{self.base_url}/v1/oauth2/token"
        basic = base64.b64encode(
            f"{client_id}:{client_secret}".encode("utf-8"),
        ).decode("ascii")
        headers = {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        try:
            response = _requests.post(  # type: ignore[union-attr]
                url,
                data={"grant_type": "client_credentials"},
                headers=headers,
                timeout=self.timeout,
            )
        except _requests.Timeout as exc:  # type: ignore[union-attr]
            raise AdapterTimeout(
                self.name,
                f"oauth2 timeout after {self.timeout}s: {exc}",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            raise AdapterUnavailable(
                self.name, f"oauth2 connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"oauth2 fetch failed: {type(exc).__name__}: {exc}",
            ) from exc

        status = getattr(response, "status_code", 0)
        if status in (401, 403):
            snippet = (getattr(response, "text", "") or "")[:200]
            raise AdapterAuthError(
                self.name,
                f"oauth2 rejected credentials ({status}): {snippet}",
            )
        if status == 429:
            raise AdapterRateLimited(
                self.name, "oauth2 rate limited (429)",
            )
        if status >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            raise AdapterError(
                self.name, f"oauth2 returned {status}: {snippet}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterError(
                self.name, f"oauth2 returned non-JSON body: {exc}",
            ) from exc

        access_token = payload.get("access_token", "") if isinstance(
            payload, dict,
        ) else ""
        if not access_token:
            raise AdapterError(
                self.name, "oauth2 response missing access_token",
            )
        expires_in = float(payload.get("expires_in", 0) or 0)
        return str(access_token), expires_in

    # ── URL builders ───────────────────────────────────────────

    def _refund_url(self, transaction_id: str) -> str:
        # PayPal's normalised "transaction_id" maps to a capture id
        # in the v2 Orders API.
        return (
            f"{self.base_url}/v2/payments/captures/"
            f"{transaction_id}/refund"
        )

    def _capture_url(self, authorization_id: str) -> str:
        return (
            f"{self.base_url}/v2/payments/authorizations/"
            f"{authorization_id}/capture"
        )

    def _disputes_url(self, params: dict[str, Any]) -> str:
        page_size = params.get("page_size")
        try:
            page_size_int = int(page_size) if page_size is not None else 20
        except (TypeError, ValueError):
            page_size_int = 20
        page_size_int = max(1, min(50, page_size_int))

        query: list[str] = [f"page_size={page_size_int}"]
        status = params.get("status")
        if status:
            query.append(f"dispute_state={status}")
        created_after = params.get("created_after")
        if created_after:
            query.append(f"update_time_after={created_after}")
        return (
            f"{self.base_url}/v1/customer/disputes?" + "&".join(query)
        )

    # ── Payload builders ───────────────────────────────────────

    def _build_refund_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        """PayPal accepts an empty body for a full refund and an
        ``amount`` block plus optional ``note_to_payer`` /
        ``invoice_id`` for partial refunds."""
        body: dict[str, Any] = {}
        amount = params.get("amount")
        if amount is not None:
            body["amount"] = {
                "value": str(amount),
                "currency_code": str(params["currency"]).upper(),
            }
        note = params.get("note")
        if note:
            body["note_to_payer"] = str(note)
        metadata = params.get("metadata") or {}
        invoice_id = (
            metadata.get("invoice_id")
            or metadata.get("order_id")
            or params.get("invoice_id")
        )
        if invoice_id:
            body["invoice_id"] = str(invoice_id)
        return body

    def _build_capture_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "final_capture": bool(params.get("is_final_capture", True)),
        }
        amount = params.get("amount")
        if amount is not None:
            body["amount"] = {
                "value": str(amount),
                "currency_code": str(params["currency"]).upper(),
            }
        note = params.get("note")
        if note:
            body["note_to_payer"] = str(note)
        return body

    # ── Response parsers ───────────────────────────────────────

    def _parse_refund_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"refund response not a dict: {type(raw).__name__}",
            )
        amount_block = raw.get("amount") or {}
        return {
            "refund_id": str(raw.get("id", "") or ""),
            "status": str(raw.get("status", "") or ""),
            "amount": str(amount_block.get("value", "") or ""),
            "currency": str(amount_block.get("currency_code", "") or ""),
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
        amount_block = raw.get("amount") or {}
        return {
            "capture_id": str(raw.get("id", "") or ""),
            "status": str(raw.get("status", "") or ""),
            "amount": str(amount_block.get("value", "") or ""),
            "currency": str(amount_block.get("currency_code", "") or ""),
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
        items = raw.get("items") or []
        normalised: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            amt = item.get("dispute_amount") or {}
            normalised.append({
                "dispute_id": str(item.get("dispute_id", "") or ""),
                "status": str(item.get("status", "") or ""),
                "reason": str(item.get("reason", "") or ""),
                "amount": str(amt.get("value", "") or ""),
                "currency": str(amt.get("currency_code", "") or ""),
                "create_time": str(item.get("create_time", "") or ""),
            })
        return {
            "disputes": normalised,
            "count": len(normalised),
        }
