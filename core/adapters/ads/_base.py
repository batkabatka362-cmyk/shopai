"""AdsBaseAdapter — shared HTTP base for ad platform adapters.

Concrete adapters (Google Ads, Meta Ads) inherit this class and
override only the vendor-specific bits:

  * ``base_url``       — vendor API root
  * ``config_alias``   — ``ENV_ALIASES`` key for the API key
  * ``_auth_headers``  — vendor-specific auth header
  * ``_create_campaign``   — create a campaign
  * ``_get_performance``   — fetch performance metrics
  * ``_update_budget``     — update campaign budget

The base handles:

  * Capability dispatch (CREATE_CAMPAIGN, GET_PERFORMANCE,
    UPDATE_BUDGET)
  * Required-field validation
  * HTTP execution with typed error mapping
  * AdapterResult assembly
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

logger = get_logger("adapters.ads")


class AdsBaseAdapter(BaseAdapter):
    """Abstract base for every ad platform adapter."""

    category = AdapterCategory.ADS
    capabilities = {
        Capability.ADS_CREATE_CAMPAIGN,
        Capability.ADS_GET_PERFORMANCE,
        Capability.ADS_UPDATE_BUDGET,
        Capability.ADS_PAUSE_CAMPAIGN,
        Capability.ADS_RESUME_CAMPAIGN,
    }

    base_url: str = ""
    config_alias: str = ""
    timeout: float = 30.0

    cost_per_call: float = 0.0

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
        dispatch = {
            Capability.ADS_GET_PERFORMANCE: self._do_get_performance,
            Capability.ADS_CREATE_CAMPAIGN: self._do_create_campaign,
            Capability.ADS_UPDATE_BUDGET: self._do_update_budget,
            Capability.ADS_PAUSE_CAMPAIGN: self._do_pause_campaign,
            Capability.ADS_RESUME_CAMPAIGN: self._do_resume_campaign,
        }
        handler = dispatch.get(capability)
        if handler is None:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )
        return handler(capability, params)

    # ── Vendor hooks (override in subclass) ────────────────────

    def _do_get_performance(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError

    def _do_create_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError

    def _do_update_budget(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError

    def _do_pause_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError

    def _do_resume_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError

    # ── HTTP ───────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

    def _http_request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        hdrs = headers or self._auth_headers()
        try:
            if method.upper() == "GET":
                response = _requests.get(url, headers=hdrs, timeout=self.timeout)
            else:
                response = _requests.post(
                    url, json=body, headers=hdrs, timeout=self.timeout,
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
                f"HTTP {method} failed: {type(exc).__name__}: {exc}",
            ) from exc

        if response.status_code >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if response.status_code in (401, 403):
                raise AdapterAuthError(self.name, f"({response.status_code}): {snippet}")
            if response.status_code == 429:
                raise AdapterRateLimited(self.name, f"rate limit (429): {snippet}")
            if 500 <= response.status_code < 600:
                raise AdapterUnavailable(
                    self.name, f"vendor 5xx ({response.status_code}): {snippet}",
                )
            raise AdapterError(
                self.name, f"vendor returned {response.status_code}: {snippet}",
            )

        try:
            return response.json() if response.text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON response: {exc}",
            ) from exc
