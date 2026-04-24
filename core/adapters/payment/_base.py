"""PaymentBaseAdapter — shared HTTP base for payment processors.

Concrete adapters (PayPal today; Stripe / Adyen later) inherit
this class and override only the vendor-specific bits:

  * ``base_url``                — vendor API root
  * ``_auth_headers``           — vendor-specific auth (PayPal
                                  needs an OAuth2 bearer token,
                                  Stripe just uses the secret key)
  * ``_refund_url``             — endpoint that creates a refund
  * ``_capture_url``            — endpoint that captures an
                                  authorisation
  * ``_disputes_url``           — endpoint that lists disputes
  * ``_build_refund_payload``   — vendor refund body
  * ``_build_capture_payload``  — vendor capture body
  * ``_parse_refund_response``  — vendor → normalised refund dict
  * ``_parse_capture_response`` — vendor → normalised capture dict
  * ``_parse_disputes_response``— vendor → normalised disputes dict

The base handles:

  * Capability dispatch (``PAYMENT_REFUND`` /
    ``PAYMENT_CAPTURE`` / ``PAYMENT_LIST_DISPUTES``)
  * Required-field validation per capability
  * HTTP POST / GET execution with typed error mapping
  * AdapterResult assembly (latency comes from the public
    ``BaseAdapter.execute`` wrapper)

Normalised parameter shapes (vendor-agnostic):

    refund:
        {
            "transaction_id": "9XJ12345AB678901C",   # required
            "amount":         "12.34",                # optional (full refund if absent)
            "currency":       "USD",                  # required when amount is set
            "reason":         "customer_request",     # optional
            "note":           "Replacement shipped",  # optional, vendor-visible
            "metadata":       {"order_id": "1001"},   # optional
        }

    capture:
        {
            "authorization_id": "8AB12345CD678901E",  # required
            "amount":           "49.99",              # optional (full auth if absent)
            "currency":         "USD",                # required when amount is set
            "is_final_capture": True,                 # optional, default True
            "note":             "Order #1001",        # optional
        }

    list_disputes:
        {
            "page_size":      20,                     # optional, default 20
            "status":         "OPEN",                 # optional filter
            "created_after":  "2024-01-01T00:00:00Z", # optional ISO 8601
        }

Normalised return shapes:

    refund result data:
        {
            "refund_id":      "5XY12345AB678901C",
            "status":         "COMPLETED",
            "amount":         "12.34",
            "currency":       "USD",
            "transaction_id": "9XJ12345AB678901C",
        }

    capture result data:
        {
            "capture_id":      "0CD12345EF678901G",
            "status":          "COMPLETED",
            "amount":          "49.99",
            "currency":        "USD",
            "authorization_id":"8AB12345CD678901E",
        }

    list_disputes result data:
        {
            "disputes":  [{"dispute_id": "...", "status": "...",
                            "reason": "...", "amount": "...",
                            "currency": "..."}],
            "count":     5,
        }

Scope note: this Wave 1 surface is intentionally narrow —
refund / capture / list disputes only. Subscription management,
payouts, webhooks, and KYC are out of scope and belong in a
later wave (or in a dedicated subscriptions adapter).
"""
from __future__ import annotations

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
    AdapterNotConfigured,
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

logger = get_logger("adapters.payment")


_DEFAULT_TIMEOUT = 20.0


class PaymentBaseAdapter(BaseAdapter):
    """Abstract base for every payment-processor adapter.

    Concrete adapters MUST set:

      * ``name``       — registry key (e.g. ``"paypal"``)
      * ``base_url``   — vendor API root

    They MAY override:

      * ``priority``      — router preference (0-100). The first
                            real-money adapter wired into the
                            store should generally win, so the
                            default here is intentionally lower
                            than email's 90 — operators wire one
                            payment processor per store, not many.
      * ``cost_per_call`` — $/call (typically 0; payment vendors
                            charge per transaction, not per API
                            request)
      * ``timeout``       — per-request timeout in seconds
    """

    category = AdapterCategory.PAYMENT
    capabilities = {
        Capability.PAYMENT_REFUND,
        Capability.PAYMENT_CAPTURE,
        Capability.PAYMENT_LIST_DISPUTES,
        Capability.PAYMENT_CREATE_ORDER,
        Capability.PAYMENT_GET_ORDER,
        Capability.PAYMENT_CAPTURE_ORDER,
        Capability.PAYMENT_PAYOUT,
        Capability.PAYMENT_LIST_TRANSACTIONS,
        Capability.PAYMENT_GET_BALANCE,
    }

    base_url: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    priority: int = 50

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        """Sub-classes override to check the vendor's specific
        credential set (e.g. PayPal needs both client id AND
        client secret). Default returns False so an unconfigured
        base class never accidentally satisfies the router."""
        return False

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability == Capability.PAYMENT_REFUND:
            return self._do_refund(params)
        if capability == Capability.PAYMENT_CAPTURE:
            return self._do_capture(params)
        if capability == Capability.PAYMENT_LIST_DISPUTES:
            return self._do_list_disputes(params)
        if capability == Capability.PAYMENT_CREATE_ORDER:
            return self._do_create_order(params)
        if capability == Capability.PAYMENT_GET_ORDER:
            return self._do_get_order(params)
        if capability == Capability.PAYMENT_CAPTURE_ORDER:
            return self._do_capture_order(params)
        if capability == Capability.PAYMENT_PAYOUT:
            return self._do_payout(params)
        if capability == Capability.PAYMENT_LIST_TRANSACTIONS:
            return self._do_list_transactions(params)
        if capability == Capability.PAYMENT_GET_BALANCE:
            return self._do_get_balance(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Orders v2 / Payouts / Balance / Txn list ─────────
    # Default implementations raise NotImplementedError so
    # each concrete adapter opt-in per capability. Sub-classes
    # that don't support a given surface are still valid —
    # they just omit the capability from their ``capabilities``
    # set + never land in the dispatcher for it.

    def _do_create_order(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{self.name}: create_order not implemented",
        )

    def _do_get_order(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{self.name}: get_order not implemented",
        )

    def _do_capture_order(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{self.name}: capture_order not implemented",
        )

    def _do_payout(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{self.name}: payout not implemented",
        )

    def _do_list_transactions(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{self.name}: list_transactions not implemented",
        )

    def _do_get_balance(
        self, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{self.name}: get_balance not implemented",
        )

    # ── Refund ─────────────────────────────────────────────────

    def _do_refund(self, params: dict[str, Any]) -> AdapterResult:
        self._validate_refund(params)
        url = self._refund_url(params["transaction_id"])
        body = self._build_refund_payload(params)
        raw = self._http_post(url, body, headers=self._auth_headers())
        normalised = self._parse_refund_response(raw, params)
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.PAYMENT_REFUND.value,
            data=normalised,
            raw=raw,
        )

    def _validate_refund(self, params: dict[str, Any]) -> None:
        tx = params.get("transaction_id")
        if not tx or not isinstance(tx, str):
            raise AdapterValidationError(
                self.name, "'transaction_id' is required for refund",
            )
        amount = params.get("amount")
        if amount is not None:
            if not params.get("currency"):
                raise AdapterValidationError(
                    self.name,
                    "'currency' is required when 'amount' is set",
                )
            try:
                amt_value = float(amount)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, f"'amount' must be numeric (got {amount!r})",
                ) from exc
            if amt_value <= 0:
                raise AdapterValidationError(
                    self.name,
                    f"'amount' must be positive (got {amt_value})",
                )

    # ── Capture ────────────────────────────────────────────────

    def _do_capture(self, params: dict[str, Any]) -> AdapterResult:
        self._validate_capture(params)
        url = self._capture_url(params["authorization_id"])
        body = self._build_capture_payload(params)
        raw = self._http_post(url, body, headers=self._auth_headers())
        normalised = self._parse_capture_response(raw, params)
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.PAYMENT_CAPTURE.value,
            data=normalised,
            raw=raw,
        )

    def _validate_capture(self, params: dict[str, Any]) -> None:
        auth_id = params.get("authorization_id")
        if not auth_id or not isinstance(auth_id, str):
            raise AdapterValidationError(
                self.name,
                "'authorization_id' is required for capture",
            )
        amount = params.get("amount")
        if amount is not None:
            if not params.get("currency"):
                raise AdapterValidationError(
                    self.name,
                    "'currency' is required when 'amount' is set",
                )
            try:
                amt_value = float(amount)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, f"'amount' must be numeric (got {amount!r})",
                ) from exc
            if amt_value <= 0:
                raise AdapterValidationError(
                    self.name,
                    f"'amount' must be positive (got {amt_value})",
                )

    # ── List disputes ──────────────────────────────────────────

    def _do_list_disputes(self, params: dict[str, Any]) -> AdapterResult:
        url = self._disputes_url(params)
        raw = self._http_get(url, headers=self._auth_headers())
        normalised = self._parse_disputes_response(raw, params)
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.PAYMENT_LIST_DISPUTES.value,
            data=normalised,
            raw=raw,
        )

    # ── Vendor-specific hooks (override in subclasses) ────────

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token via ``_bearer_token``. Override
        when the vendor uses Basic auth or a custom header."""
        return {
            "Authorization": f"Bearer {self._bearer_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _bearer_token(self) -> str:
        """Return a fresh bearer token. PayPal's OAuth2 flow
        overrides this; vendors that use a static secret key
        (Stripe-style) override it to return that key directly."""
        raise NotImplementedError(
            f"{type(self).__name__}._bearer_token must be implemented",
        )

    def _refund_url(self, transaction_id: str) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}._refund_url must be implemented",
        )

    def _capture_url(self, authorization_id: str) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}._capture_url must be implemented",
        )

    def _disputes_url(self, params: dict[str, Any]) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}._disputes_url must be implemented",
        )

    def _build_refund_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._build_refund_payload must be implemented",
        )

    def _build_capture_payload(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._build_capture_payload must be implemented",
        )

    def _parse_refund_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._parse_refund_response must be implemented",
        )

    def _parse_capture_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._parse_capture_response must be implemented",
        )

    def _parse_disputes_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._parse_disputes_response must be implemented",
        )

    # ── HTTP ───────────────────────────────────────────────────

    def _http_post(
        self,
        url: str,
        body: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> Any:
        return self._http_request("POST", url, headers, body)

    def _http_get(
        self,
        url: str,
        headers: dict[str, str],
    ) -> Any:
        return self._http_request("GET", url, headers, None)

    def _http_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any] | None,
    ) -> Any:
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        try:
            if method == "GET":
                response = _requests.get(
                    url, headers=headers, timeout=self.timeout,
                )
            else:
                response = _requests.request(
                    method, url, json=body, headers=headers,
                    timeout=self.timeout,
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
                f"http {method.lower()} failed: {type(exc).__name__}: {exc}",
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
