"""ShippingBaseAdapter — shared HTTP base for carrier adapters.

Concrete adapters (EasyPost, Shippo, …) inherit this class and
override only the vendor-specific bits:

  * ``base_url``            — carrier API endpoint
  * ``config_alias``        — API key env alias
  * ``_build_auth_headers`` — vendor-specific auth header shape
  * ``_build_shipment``     — from/to/parcel → vendor payload
  * ``_parse_rates``        — vendor response → list of
                               ``ShippingRate`` dicts
  * ``_build_buy_payload``  — rate_id → vendor "buy label" body
  * ``_parse_label``        — vendor buy response → label dict

The base handles:

  * Validation of ``from_address`` / ``to_address`` / ``parcel``
  * HTTP POST + error mapping
  * Rate list normalisation + sort by price
  * AdapterResult assembly with latency / cost metadata

Normalised shapes:

    from_address / to_address
        {
            "name":     "Acme Warehouse",      # optional
            "street1":  "123 Main St",
            "street2":  "",                    # optional
            "city":     "Seattle",
            "state":    "WA",
            "zip":      "98101",
            "country":  "US",                  # ISO 2-letter
            "phone":    "",                    # optional
            "email":    "",                    # optional
        }

    parcel
        {
            "length":  10.0,   # inches
            "width":   8.0,
            "height":  4.0,
            "weight":  16.0,   # ounces
        }

    ShippingRate (normalised output)
        {
            "rate_id":       "rate_abc123",
            "carrier":       "USPS",
            "service":       "Priority",
            "rate":          8.95,      # USD
            "currency":      "USD",
            "delivery_days": 3,         # nullable
            "delivery_date": "",        # ISO, nullable
        }
"""
from __future__ import annotations

from typing import Any, TypedDict

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

logger = get_logger("adapters.shipping")


class ShippingRate(TypedDict):
    """One normalised shipping rate quote."""

    rate_id: str
    carrier: str
    service: str
    rate: float
    currency: str
    delivery_days: int
    delivery_date: str


_REQUIRED_ADDRESS_FIELDS = ("street1", "city", "zip", "country")
_REQUIRED_PARCEL_FIELDS = ("length", "width", "height", "weight")

_DEFAULT_TIMEOUT = 20.0


class ShippingBaseAdapter(BaseAdapter):
    """Abstract base for every shipping adapter.

    Concrete adapters MUST set:

      * ``name``           — registry key
      * ``base_url``       — carrier API root
      * ``config_alias``   — env var alias for the API key

    They MAY override:

      * ``priority``            — router preference (0-100)
      * ``cost_per_call``       — $/call (rate quotes are free,
                                  label buys cost actual postage)
      * ``free_tier_*``         — quota hints for the metrics layer
      * ``extra_headers()``     — non-auth headers
    """

    category = AdapterCategory.LOGISTICS
    capabilities = {
        Capability.SHIPPING_RATE_QUOTE,
        Capability.SHIPPING_LABEL_BUY,
    }

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    free_tier_daily_limit: int = 0
    free_tier_monthly_limit: int = 0

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url or not self.config_alias:
            return False
        return bool(get_config().get(self.config_alias))

    def _api_key(self) -> str:
        key = get_config().get(self.config_alias)
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability == Capability.SHIPPING_RATE_QUOTE:
            return self._quote_rates(params)
        if capability == Capability.SHIPPING_LABEL_BUY:
            return self._buy_label(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Rate quote ─────────────────────────────────────────────

    def _quote_rates(self, params: dict[str, Any]) -> AdapterResult:
        from_address = params.get("from_address")
        to_address = params.get("to_address")
        parcel = params.get("parcel")

        self._validate_address(from_address, label="from_address")
        self._validate_address(to_address, label="to_address")
        self._validate_parcel(parcel)

        body = self._build_shipment(from_address, to_address, parcel)
        raw = self._http_post(
            self._rate_quote_url(),
            body,
            headers=self._auth_headers(),
        )
        rates = self._parse_rates(raw)
        rates_sorted = sorted(rates, key=lambda r: float(r.get("rate", 0) or 0))

        cheapest = rates_sorted[0] if rates_sorted else None
        fastest = self._fastest_rate(rates_sorted)

        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.SHIPPING_RATE_QUOTE.value,
            data={
                "rates": rates_sorted,
                "count": len(rates_sorted),
                "cheapest": cheapest,
                "fastest": fastest,
                "shipment_id": self._extract_shipment_id(raw),
            },
            raw=raw,
        )

    # ── Buy label ──────────────────────────────────────────────

    def _buy_label(self, params: dict[str, Any]) -> AdapterResult:
        rate_id = params.get("rate_id")
        shipment_id = params.get("shipment_id")
        if not rate_id:
            raise AdapterValidationError(
                self.name, "'rate_id' is required to buy a label",
            )

        body = self._build_buy_payload(rate_id, shipment_id, params)
        raw = self._http_post(
            self._buy_url(shipment_id),
            body,
            headers=self._auth_headers(),
        )
        label = self._parse_label(raw)
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.SHIPPING_LABEL_BUY.value,
            data=label,
            raw=raw,
        )

    # ── Vendor-specific hooks (override in subclasses) ────────

    def _rate_quote_url(self) -> str:
        """Default rate quote endpoint — override if the vendor
        uses a different path."""
        raise NotImplementedError(
            f"{type(self).__name__}._rate_quote_url must be implemented",
        )

    def _buy_url(self, shipment_id: str | None) -> str:
        """Default buy-label endpoint — override if the vendor
        uses a different path."""
        raise NotImplementedError(
            f"{type(self).__name__}._buy_url must be implemented",
        )

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token. Override when the vendor uses
        a different auth scheme (Basic, X-API-Key, etc.)."""
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

    def _build_shipment(
        self,
        from_address: dict[str, Any],
        to_address: dict[str, Any],
        parcel: dict[str, Any],
    ) -> dict[str, Any]:
        """Translate the normalised shapes into the vendor's
        request body. MUST be overridden."""
        raise NotImplementedError(
            f"{type(self).__name__}._build_shipment must be implemented",
        )

    def _parse_rates(self, raw: Any) -> list[dict[str, Any]]:
        """Translate the vendor's response into a list of
        ``ShippingRate`` dicts. MUST be overridden."""
        raise NotImplementedError(
            f"{type(self).__name__}._parse_rates must be implemented",
        )

    def _build_buy_payload(
        self,
        rate_id: str,
        shipment_id: str | None,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Translate rate_id into the vendor's buy-label body.
        MUST be overridden."""
        raise NotImplementedError(
            f"{type(self).__name__}._build_buy_payload must be implemented",
        )

    def _parse_label(self, raw: Any) -> dict[str, Any]:
        """Translate the vendor's buy response into a normalised
        label dict. MUST be overridden."""
        raise NotImplementedError(
            f"{type(self).__name__}._parse_label must be implemented",
        )

    def _extract_shipment_id(self, raw: Any) -> str:
        """Return the shipment identifier from the quote
        response so the caller can later buy a label against
        it. Default: empty string — override when the vendor
        requires shipment_id for buy."""
        return ""

    @staticmethod
    def _fastest_rate(
        rates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return the rate with the lowest ``delivery_days``
        value. Ties broken by price (cheaper wins)."""
        if not rates:
            return None
        eligible = [
            r for r in rates
            if isinstance(r.get("delivery_days"), (int, float))
            and r["delivery_days"] > 0
        ]
        if not eligible:
            return rates[0]
        return min(
            eligible,
            key=lambda r: (int(r["delivery_days"]), float(r.get("rate", 0) or 0)),
        )

    # ── Validation ─────────────────────────────────────────────

    def _validate_address(
        self,
        address: Any,
        *,
        label: str,
    ) -> None:
        if not isinstance(address, dict):
            raise AdapterValidationError(
                self.name, f"'{label}' must be a dict",
            )
        missing = [
            f for f in _REQUIRED_ADDRESS_FIELDS
            if not address.get(f)
        ]
        if missing:
            raise AdapterValidationError(
                self.name,
                f"'{label}' missing required fields: {', '.join(missing)}",
            )

    def _validate_parcel(self, parcel: Any) -> None:
        if not isinstance(parcel, dict):
            raise AdapterValidationError(
                self.name, "'parcel' must be a dict",
            )
        missing = [
            f for f in _REQUIRED_PARCEL_FIELDS
            if parcel.get(f) is None
        ]
        if missing:
            raise AdapterValidationError(
                self.name,
                f"'parcel' missing required fields: {', '.join(missing)}",
            )
        for field in _REQUIRED_PARCEL_FIELDS:
            try:
                value = float(parcel[field])
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"parcel.{field} must be numeric",
                ) from exc
            if value <= 0:
                raise AdapterValidationError(
                    self.name,
                    f"parcel.{field} must be positive (got {value})",
                )

    # ── HTTP ───────────────────────────────────────────────────

    def _http_post(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        try:
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

        if response.status_code >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if response.status_code in (401, 403):
                raise AdapterAuthError(
                    self.name,
                    f"vendor rejected credentials "
                    f"({response.status_code}): {snippet}",
                )
            if response.status_code == 429:
                raise AdapterRateLimited(
                    self.name, f"rate limit (429): {snippet}",
                )
            if 500 <= response.status_code < 600:
                raise AdapterUnavailable(
                    self.name,
                    f"vendor 5xx ({response.status_code}): {snippet}",
                )
            raise AdapterError(
                self.name,
                f"vendor returned {response.status_code}: {snippet}",
            )

        try:
            return response.json()
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON response: {exc}",
            ) from exc
