"""AnalyticsBaseAdapter -- HTTP base for analytics
ingestion sinks (GA4 Measurement Protocol, Mixpanel,
Posthog, etc.).

Concrete adapters override:
  - base_url + paths
  - _auth_or_query (some vendors use API key in query,
    others Bearer)
  - _build_event_payload (vendor-specific event shape)
  - _build_identify_payload (when supported)
  - _build_query_payload (when supported; many sinks are
    write-only)
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

logger = get_logger("adapters.analytics")


class AnalyticsBaseAdapter(BaseAdapter):
    """Abstract base for every analytics adapter."""

    category = AdapterCategory.ANALYTICS
    capabilities = {
        Capability.ANALYTICS_TRACK_EVENT,
        Capability.ANALYTICS_IDENTIFY,
    }

    base_url: str = ""
    config_alias: str = ""
    timeout: float = 15.0
    cost_per_call: float = 0.0

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url or not self.config_alias:
            return False
        return bool(
            _resolve_per_store(self.config_alias)
            or get_config().get(self.config_alias)
        )

    def _api_key(self) -> str:
        key = (
            _resolve_per_store(self.config_alias)
            or get_config().get(self.config_alias)
        )
        if not key:
            env = get_config().env_var_for(
                self.config_alias,
            )
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Dispatch ──────────────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability == Capability.ANALYTICS_TRACK_EVENT:
            return self._do_track_event(
                capability, params,
            )
        if capability == Capability.ANALYTICS_IDENTIFY:
            return self._do_identify(capability, params)
        return AdapterResult.failure(
            self.name, capability.value,
            AdapterValidationError(
                self.name,
                f"unsupported capability {capability.value}",
            ),
        )

    # ── TRACK_EVENT ────────────────────────────────────────────

    def _do_track_event(
        self, capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        event_name = str(
            params.get("event_name") or "",
        ).strip()
        if not event_name:
            raise AdapterValidationError(
                self.name, "event_name required",
            )
        user_id = str(
            params.get("user_id")
            or params.get("client_id")
            or "",
        )
        if not user_id:
            raise AdapterValidationError(
                self.name,
                "user_id or client_id required",
            )
        path = self._track_event_path()
        payload = self._build_event_payload(
            event_name=event_name,
            user_id=user_id,
            event_params=params.get(
                "event_params", {},
            ),
            timestamp_micros=params.get(
                "timestamp_micros", 0,
            ),
        )
        result = self._post(capability, path, payload)
        if not result.ok:
            return result
        return AdapterResult.success(
            self.name, capability.value,
            data={
                "event_sent": True,
                "event_name": event_name,
                "user_id": user_id,
            },
            latency_ms=result.latency_ms,
            cost_usd=self.cost_per_call,
        )

    # ── IDENTIFY ──────────────────────────────────────────────

    def _do_identify(
        self, capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        user_id = str(
            params.get("user_id")
            or params.get("client_id")
            or "",
        )
        if not user_id:
            raise AdapterValidationError(
                self.name, "user_id required",
            )
        path = self._identify_path()
        payload = self._build_identify_payload(
            user_id=user_id,
            traits=params.get("traits", {}),
        )
        result = self._post(capability, path, payload)
        if not result.ok:
            return result
        return AdapterResult.success(
            self.name, capability.value,
            data={
                "identified": True,
                "user_id": user_id,
            },
            latency_ms=result.latency_ms,
            cost_usd=self.cost_per_call,
        )

    # ── Vendor-specific hooks ─────────────────────────────────

    def _track_event_path(self) -> str:
        raise NotImplementedError

    def _build_event_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _identify_path(self) -> str:
        raise NotImplementedError

    def _build_identify_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    # ── HTTP ─────────────────────────────────────────────────

    def _post(
        self, capability: Capability,
        path: str, payload: dict[str, Any],
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

    def _normalise_http_response(
        self, capability: Capability,
        resp: Any, latency_ms: float,
    ) -> AdapterResult:
        status = resp.status_code
        body_text = resp.text or ""
        if status in (401, 403):
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
        # GA4 Measurement Protocol returns 204 No
        # Content on success with empty body.
        try:
            data = resp.json() if body_text else {}
        except Exception:  # noqa: BLE001
            data = {"raw": body_text}
        return AdapterResult.success(
            self.name, capability.value,
            data=data, latency_ms=round(latency_ms, 2),
        )
