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

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
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

    # ── Orders v2 (PayPal Checkout flow) ───────────────────────

    def _do_create_order(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        """Create a PayPal order. Params:

          * ``amount`` — numeric, required. Total charge.
          * ``currency`` — e.g. ``"USD"``. Default ``"USD"``.
          * ``reference_id`` — optional merchant-side id
            (Shopify order id). Echoes back on capture so
            we can correlate.
          * ``description`` — human-visible checkout label.
          * ``return_url`` / ``cancel_url`` — required if we
            want buyer redirected back to the storefront.
          * ``brand_name`` — shown on PayPal's UI.
        """
        if params.get("amount") is None:
            raise AdapterValidationError(
                self.name, "'amount' is required",
            )
        try:
            amount = float(params["amount"])
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                f"'amount' must be numeric (got {params['amount']!r})",
            ) from exc
        if amount <= 0:
            raise AdapterValidationError(
                self.name, "'amount' must be > 0",
            )

        currency = str(
            params.get("currency") or "USD",
        ).upper()
        body: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {
                        "currency_code": currency,
                        "value": f"{amount:.2f}",
                    },
                },
            ],
        }
        unit = body["purchase_units"][0]
        if params.get("reference_id"):
            unit["reference_id"] = str(params["reference_id"])
        if params.get("description"):
            unit["description"] = str(params["description"])
        if any(
            params.get(k)
            for k in (
                "return_url", "cancel_url", "brand_name",
            )
        ):
            body["application_context"] = {}
            ac = body["application_context"]
            if params.get("return_url"):
                ac["return_url"] = str(params["return_url"])
            if params.get("cancel_url"):
                ac["cancel_url"] = str(params["cancel_url"])
            if params.get("brand_name"):
                ac["brand_name"] = str(params["brand_name"])

        url = f"{self.base_url}/v2/checkout/orders"
        raw = self._http_post(
            url, body, headers=self._auth_headers(),
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.PAYMENT_CREATE_ORDER.value,
            data=self._parse_order(raw),
            raw=raw,
        )

    def _do_get_order(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        oid = str(params.get("order_id") or "").strip()
        if not oid:
            raise AdapterValidationError(
                self.name, "'order_id' is required",
            )
        url = f"{self.base_url}/v2/checkout/orders/{oid}"
        raw = self._http_get(url, self._auth_headers())
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.PAYMENT_GET_ORDER.value,
            data=self._parse_order(raw),
            raw=raw,
        )

    def _do_capture_order(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        """Capture an approved order. PayPal's capture
        endpoint is idempotent — same request twice returns
        the original capture id (§4b.D).
        """
        oid = str(params.get("order_id") or "").strip()
        if not oid:
            raise AdapterValidationError(
                self.name, "'order_id' is required",
            )
        url = (
            f"{self.base_url}/v2/checkout/orders/{oid}/"
            "capture"
        )
        # Empty body is valid for CAPTURE intent orders
        raw = self._http_post(
            url, None, headers=self._auth_headers(),
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.PAYMENT_CAPTURE_ORDER.value,
            data=self._parse_order(raw),
            raw=raw,
        )

    # ── Payouts (send money out) ───────────────────────────────

    def _do_payout(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        """Send money from the merchant's PayPal balance to
        one or more recipients. Owner-driven — expected to
        be gated by risk_gate at call sites (payout is a
        HIGH action).

        Params:
          * ``items`` — list of
            ``{recipient_email, amount, currency?, note?,
              sender_item_id?}``. Required.
          * ``email_subject`` — subject line on PayPal's
            email notification. Optional.
          * ``batch_id`` — our-side sender_batch_id for
            idempotency. Required.
        """
        items = params.get("items") or []
        if not isinstance(items, list) or not items:
            raise AdapterValidationError(
                self.name, "'items' non-empty list required",
            )
        batch_id = str(params.get("batch_id") or "").strip()
        if not batch_id:
            raise AdapterValidationError(
                self.name, "'batch_id' is required",
            )
        items_out: list[dict[str, Any]] = []
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                raise AdapterValidationError(
                    self.name,
                    f"items[{i}] must be a dict",
                )
            email = str(it.get("recipient_email") or "").strip()
            if not email:
                raise AdapterValidationError(
                    self.name,
                    f"items[{i}] 'recipient_email' required",
                )
            try:
                amt = float(it.get("amount") or 0)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"items[{i}] 'amount' must be numeric",
                ) from exc
            if amt <= 0:
                raise AdapterValidationError(
                    self.name,
                    f"items[{i}] 'amount' must be > 0",
                )
            row: dict[str, Any] = {
                "recipient_type": "EMAIL",
                "receiver": email,
                "amount": {
                    "value": f"{amt:.2f}",
                    "currency": str(
                        it.get("currency") or "USD",
                    ).upper(),
                },
            }
            if it.get("note"):
                row["note"] = str(it["note"])
            if it.get("sender_item_id"):
                row["sender_item_id"] = str(
                    it["sender_item_id"],
                )
            items_out.append(row)

        body: dict[str, Any] = {
            "sender_batch_header": {
                "sender_batch_id": batch_id,
                "email_subject": str(
                    params.get("email_subject")
                    or "You have a payment from Deguar",
                ),
            },
            "items": items_out,
        }
        url = f"{self.base_url}/v1/payments/payouts"
        raw = self._http_post(
            url, body, headers=self._auth_headers(),
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.PAYMENT_PAYOUT.value,
            data=self._parse_payout(raw),
            raw=raw,
        )

    # ── Read-only (transactions + balance) ────────────────────

    def _do_list_transactions(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        """List recent transactions via the Reporting API.
        Params:

          * ``start_date`` / ``end_date`` — ISO-8601 strings.
            Defaults: last 7 days.
          * ``page_size`` — 1-500. Default 50.
        """
        start = str(params.get("start_date") or "").strip()
        end = str(params.get("end_date") or "").strip()
        if not start or not end:
            import datetime as _dt
            now = _dt.datetime.now(_dt.timezone.utc)
            end = end or now.strftime(
                "%Y-%m-%dT%H:%M:%S-0000",
            )
            start = start or (
                now - _dt.timedelta(days=7)
            ).strftime("%Y-%m-%dT%H:%M:%S-0000")
        try:
            page_size = max(
                1, min(int(params.get("page_size", 50)), 500),
            )
        except (TypeError, ValueError):
            page_size = 50
        import urllib.parse as _qs
        url = (
            f"{self.base_url}/v1/reporting/transactions?"
            + _qs.urlencode({
                "start_date": start,
                "end_date": end,
                "page_size": page_size,
                "fields": "transaction_info,payer_info",
            })
        )
        raw = self._http_get(url, self._auth_headers())
        return AdapterResult.success(
            adapter=self.name,
            capability=(
                Capability.PAYMENT_LIST_TRANSACTIONS.value
            ),
            data=self._parse_transactions(raw),
            raw=raw,
        )

    def _do_get_balance(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        """Return the merchant's PayPal balance per currency.
        Read-only. Uses the Reporting API's balances endpoint."""
        url = f"{self.base_url}/v1/reporting/balances"
        currency = str(
            params.get("currency") or "",
        ).strip().upper()
        if currency:
            import urllib.parse as _qs
            url += "?" + _qs.urlencode(
                {"currency_code": currency},
            )
        raw = self._http_get(url, self._auth_headers())
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.PAYMENT_GET_BALANCE.value,
            data=self._parse_balance(raw),
            raw=raw,
        )

    # ── Response parsers (stateless, testable) ────────────────

    def _parse_order(
        self, raw: Any,
    ) -> dict[str, Any]:
        """Normalise /v2/checkout/orders response. Covers
        create / get / capture all in one shape — PayPal
        returns similar envelopes for each stage."""
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"order response not a dict: "
                f"{type(raw).__name__}",
            )
        approve_url = ""
        for link in (raw.get("links") or []):
            if not isinstance(link, dict):
                continue
            rel = str(link.get("rel") or "")
            if rel in ("approve", "payer-action"):
                approve_url = str(link.get("href") or "")
                break

        capture_id = ""
        captured_amount = ""
        captured_currency = ""
        units = raw.get("purchase_units") or []
        if units and isinstance(units[0], dict):
            payments = (
                units[0].get("payments") or {}
            )
            if isinstance(payments, dict):
                caps = payments.get("captures") or []
                if caps and isinstance(caps[0], dict):
                    cap0 = caps[0]
                    capture_id = str(cap0.get("id") or "")
                    amt = cap0.get("amount") or {}
                    captured_amount = str(
                        amt.get("value") or "",
                    )
                    captured_currency = str(
                        amt.get("currency_code") or "",
                    )

        return {
            "order_id": str(raw.get("id") or ""),
            "status": str(raw.get("status") or ""),
            "approve_url": approve_url,
            "capture_id": capture_id,
            "captured_amount": captured_amount,
            "captured_currency": captured_currency,
        }

    def _parse_payout(
        self, raw: Any,
    ) -> dict[str, Any]:
        """Normalise /v1/payments/payouts response."""
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"payout response not a dict: "
                f"{type(raw).__name__}",
            )
        header = raw.get("batch_header") or {}
        return {
            "payout_batch_id": str(
                header.get("payout_batch_id") or "",
            ),
            "batch_status": str(
                header.get("batch_status") or "",
            ),
            "sender_batch_id": str(
                (
                    header.get("sender_batch_header") or {}
                ).get("sender_batch_id") or "",
            ),
            "items_count": len(raw.get("items") or []),
        }

    def _parse_transactions(
        self, raw: Any,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                "transactions response not a dict",
            )
        details = raw.get("transaction_details") or []
        out: list[dict[str, Any]] = []
        for row in details:
            if not isinstance(row, dict):
                continue
            info = row.get("transaction_info") or {}
            payer = (row.get("payer_info") or {})
            amt = info.get("transaction_amount") or {}
            out.append({
                "id": str(
                    info.get("transaction_id") or "",
                ),
                "status": str(
                    info.get("transaction_status") or "",
                ),
                "event_code": str(
                    info.get("transaction_event_code") or "",
                ),
                "amount": str(amt.get("value") or ""),
                "currency": str(
                    amt.get("currency_code") or "",
                ),
                "initiation_date": str(
                    info.get("transaction_initiation_date")
                    or "",
                ),
                "payer_email": str(
                    payer.get("email_address") or "",
                ),
                "payer_name": str(
                    (
                        payer.get("payer_name") or {}
                    ).get("alternate_full_name") or "",
                ),
            })
        return {
            "transactions": out,
            "count": len(out),
            "start_date": str(raw.get("account_number") or ""),
        }

    def _parse_balance(
        self, raw: Any,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                "balance response not a dict",
            )
        balances = raw.get("balances") or []
        out: list[dict[str, Any]] = []
        for b in balances:
            if not isinstance(b, dict):
                continue
            total = b.get("total_balance") or {}
            available = b.get("available_balance") or {}
            out.append({
                "currency": str(
                    b.get("currency") or "",
                ),
                "total_value": str(
                    total.get("value") or "",
                ),
                "available_value": str(
                    available.get("value") or "",
                ),
                "primary": bool(b.get("primary")),
            })
        return {
            "balances": out,
            "count": len(out),
            "as_of_time": str(raw.get("as_of_time") or ""),
        }
