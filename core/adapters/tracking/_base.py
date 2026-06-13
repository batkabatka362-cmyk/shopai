"""TrackingBaseAdapter -- shared HTTP base for tracking
aggregators (AfterShip, 17track, etc.).

Concrete adapters override:
  - base_url
  - config_alias
  - _auth_headers
  - _register_payload / _parse_register_response
  - _lookup_path / _parse_lookup_response
  - _list_path / _parse_list_response

Base handles:
  - Capability dispatch for TRACKING_REGISTER /
    TRACKING_LOOKUP / TRACKING_LIST_RECENT
  - Validation (tracking_number + carrier_slug)
  - HTTP execution with typed error mapping
  - AdapterResult assembly

Normalised shapes:

  TrackingStatus (output):
    {
      "tracking_number": "1Z999AA10123456784",
      "carrier":         "ups",
      "status":          "in_transit",
      "status_detail":   "Out for delivery",
      "expected_delivery": "2026-06-15",
      "events":          [
          {
              "timestamp": "2026-06-12T14:32:00Z",
              "location":  "Chicago, IL",
              "message":   "Departed facility",
          },
          ...
      ],
      "last_updated":    "2026-06-12T14:32:00Z",
    }
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
from .._per_store_credentials import (
    resolve_per_store as _resolve_per_store,
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

logger = get_logger("adapters.tracking")


# Normalised status codes (aggregator-agnostic).
# Vendor-specific codes map to these via
# _normalise_status() per adapter.
STATUS_PENDING = "pending"        # carrier hasn't picked up yet
STATUS_INFO_RECEIVED = "info_received"  # label created, carrier notified
STATUS_IN_TRANSIT = "in_transit"
STATUS_OUT_FOR_DELIVERY = "out_for_delivery"
STATUS_DELIVERED = "delivered"
STATUS_AVAILABLE_FOR_PICKUP = "available_for_pickup"
STATUS_EXCEPTION = "exception"     # damaged / lost / stuck
STATUS_EXPIRED = "expired"
STATUS_UNKNOWN = "unknown"


class TrackingBaseAdapter(BaseAdapter):
    """Abstract base for every tracking aggregator."""

    category = AdapterCategory.TRACKING
    capabilities = {
        Capability.TRACKING_REGISTER,
        Capability.TRACKING_LOOKUP,
        Capability.TRACKING_LIST_RECENT,
    }

    base_url: str = ""
    config_alias: str = ""
    timeout: float = 20.0

    cost_per_call: float = 0.0

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url or not self.config_alias:
            return False
        # W963-117: per-store + fleet fallback (consistent
        # with all other adapter bases)
        return bool(
            _resolve_per_store(self.config_alias)
            or get_config().get(self.config_alias)
        )

    def _api_key(self) -> str:
        from .._per_store_credentials import resolve_per_store
        key = (
            resolve_per_store(self.config_alias)
            or get_config().get(self.config_alias)
        )
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    def _auth_headers(self) -> dict[str, str]:
        """Override per vendor (e.g. AfterShip uses
        aftership-api-key header)."""
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability == Capability.TRACKING_REGISTER:
            return self._do_register(capability, params)
        if capability == Capability.TRACKING_LOOKUP:
            return self._do_lookup(capability, params)
        if capability == Capability.TRACKING_LIST_RECENT:
            return self._do_list_recent(
                capability, params,
            )
        return AdapterResult.failure(
            self.name, capability.value,
            AdapterValidationError(
                self.name,
                f"unsupported capability {capability.value}",
            ),
        )

    # ── REGISTER ──────────────────────────────────────────────

    def _do_register(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        tracking_number = (
            params.get("tracking_number") or ""
        ).strip()
        carrier = (params.get("carrier") or "").strip()
        if not tracking_number:
            raise AdapterValidationError(
                self.name, "tracking_number required",
            )
        if not carrier:
            raise AdapterValidationError(
                self.name, "carrier (slug) required",
            )
        payload = self._register_payload(
            tracking_number=tracking_number,
            carrier=carrier,
            title=params.get("title", ""),
            customer_email=params.get(
                "customer_email", "",
            ),
            customer_phone=params.get(
                "customer_phone", "",
            ),
            order_id=params.get("order_id", ""),
        )
        path = self._register_path()
        result = self._post(
            capability, path, payload,
        )
        if not result.ok:
            return result
        data = self._parse_register_response(
            result.data or {},
        )
        return AdapterResult.success(
            self.name,
            capability.value,
            data=data,
            latency_ms=result.latency_ms,
            cost_usd=self.cost_per_call,
        )

    # ── LOOKUP ────────────────────────────────────────────────

    def _do_lookup(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        tracking_number = (
            params.get("tracking_number") or ""
        ).strip()
        carrier = (params.get("carrier") or "").strip()
        if not tracking_number:
            raise AdapterValidationError(
                self.name, "tracking_number required",
            )
        if not carrier:
            raise AdapterValidationError(
                self.name, "carrier (slug) required",
            )
        path = self._lookup_path(
            tracking_number=tracking_number,
            carrier=carrier,
        )
        result = self._get(capability, path)
        if not result.ok:
            return result
        data = self._parse_lookup_response(
            result.data or {},
        )
        return AdapterResult.success(
            self.name,
            capability.value,
            data=data,
            latency_ms=result.latency_ms,
            cost_usd=self.cost_per_call,
        )

    # ── LIST RECENT ───────────────────────────────────────────

    def _do_list_recent(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        limit = int(params.get("limit") or 50)
        path = self._list_path(limit=limit)
        result = self._get(capability, path)
        if not result.ok:
            return result
        data = self._parse_list_response(
            result.data or {},
        )
        return AdapterResult.success(
            self.name,
            capability.value,
            data=data,
            latency_ms=result.latency_ms,
            cost_usd=self.cost_per_call,
        )

    # ── Vendor-specific hooks (override per adapter) ──────────

    def _register_path(self) -> str:
        raise NotImplementedError

    def _register_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _parse_register_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _lookup_path(
        self, *, tracking_number: str, carrier: str,
    ) -> str:
        raise NotImplementedError

    def _parse_lookup_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _list_path(self, *, limit: int) -> str:
        raise NotImplementedError

    def _parse_list_response(
        self, raw: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    # ── HTTP plumbing ─────────────────────────────────────────

    def _post(
        self,
        capability: Capability,
        path: str,
        payload: dict[str, Any],
    ) -> AdapterResult:
        import time
        start = time.monotonic()
        url = self.base_url.rstrip("/") + path
        try:
            resp = _requests.post(
                url, headers=self._auth_headers(),
                json=payload, timeout=self.timeout,
            )
        except _requests.exceptions.Timeout as exc:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterTimeout(self.name, str(exc)),
            )
        except _requests.exceptions.RequestException as exc:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterUnavailable(self.name, str(exc)),
            )
        elapsed = (time.monotonic() - start) * 1000
        return self._normalise_http_response(
            capability, resp, elapsed,
        )

    def _get(
        self, capability: Capability, path: str,
    ) -> AdapterResult:
        import time
        start = time.monotonic()
        url = self.base_url.rstrip("/") + path
        try:
            resp = _requests.get(
                url, headers=self._auth_headers(),
                timeout=self.timeout,
            )
        except _requests.exceptions.Timeout as exc:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterTimeout(self.name, str(exc)),
            )
        except _requests.exceptions.RequestException as exc:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterUnavailable(self.name, str(exc)),
            )
        elapsed = (time.monotonic() - start) * 1000
        return self._normalise_http_response(
            capability, resp, elapsed,
        )

    def _normalise_http_response(
        self,
        capability: Capability,
        resp: Any,
        latency_ms: float,
    ) -> AdapterResult:
        status = resp.status_code
        body_text = resp.text or ""
        if status == 401 or status == 403:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterAuthError(
                    self.name, body_text[:240],
                ),
                latency_ms=round(latency_ms, 2),
            )
        if status == 429:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterRateLimited(
                    self.name, body_text[:240],
                ),
                latency_ms=round(latency_ms, 2),
            )
        if status >= 500:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterUnavailable(
                    self.name, body_text[:240],
                ),
                latency_ms=round(latency_ms, 2),
            )
        if status >= 400:
            return AdapterResult.failure(
                self.name, capability.value,
                AdapterError(
                    self.name, body_text[:240],
                ),
                latency_ms=round(latency_ms, 2),
            )
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = {"raw": body_text}
        return AdapterResult.success(
            self.name, capability.value,
            data=data, latency_ms=round(latency_ms, 2),
        )
