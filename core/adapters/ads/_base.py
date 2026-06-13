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
        return bool((_resolve_per_store(self.config_alias) or get_config().get(self.config_alias)))

    def _api_key(self) -> str:
        key = (_resolve_per_store(self.config_alias) or get_config().get(self.config_alias))
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
        max_retries: int = 3,
    ) -> Any:
        """W962-64: parity retry on 429 + 5xx + transient
        transport errors (Timeout, ConnectionError, ChunkedEnc,
        SSLError, urllib3 ProtocolError). Mirrors the
        shopify_graphql client's behaviour.

        Pre-fix the ads/email/shipping/llm bases raised
        immediately on any transient failure -- the router's
        fallback chain doesn't help because every ads adapter
        uses the same vendor endpoint."""
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        import time as _t
        hdrs = headers or self._auth_headers()
        last_exc: Exception | None = None
        for attempt in range(1, max(1, max_retries) + 1):
            try:
                if method.upper() == "GET":
                    response = _requests.get(
                        url, headers=hdrs, timeout=self.timeout,
                    )
                else:
                    response = _requests.post(
                        url, json=body, headers=hdrs,
                        timeout=self.timeout,
                    )
            except _requests.Timeout as exc:  # type: ignore[union-attr]
                last_exc = exc
                if attempt < max_retries:
                    _t.sleep(min(2 ** attempt, 8))
                    continue
                raise AdapterTimeout(
                    self.name,
                    f"timeout after {self.timeout}s: {exc}",
                ) from exc
            except _requests.ConnectionError as exc:  # type: ignore[union-attr]
                last_exc = exc
                if attempt < max_retries:
                    _t.sleep(min(2 ** attempt, 8))
                    continue
                raise AdapterUnavailable(
                    self.name, f"connection error: {exc}",
                ) from exc
            except Exception as exc:  # noqa: BLE001
                # Transient transport errors (ChunkedEncoding,
                # SSL, urllib3 ProtocolError) -- retry once.
                last_exc = exc
                msg = str(exc).lower()
                if any(s in msg for s in (
                    "chunkedencoding", "ssl", "protocol",
                    "remote disconnected",
                )) and attempt < max_retries:
                    _t.sleep(min(2 ** attempt, 8))
                    continue
                raise AdapterError(
                    self.name,
                    f"HTTP {method} failed: {type(exc).__name__}: {exc}",
                ) from exc

            if response.status_code >= 400:
                snippet = (getattr(response, "text", "") or "")[:200]
                if response.status_code in (401, 403):
                    raise AdapterAuthError(self.name, f"({response.status_code}): {snippet}")
                if response.status_code == 429:
                    # Honor Retry-After header if present.
                    retry_after = response.headers.get(
                        "Retry-After", "1",
                    )
                    try:
                        wait = float(retry_after)
                    except (TypeError, ValueError):
                        wait = 1.0
                    if attempt < max_retries:
                        _t.sleep(min(wait, 30))
                        continue
                    raise AdapterRateLimited(self.name, f"rate limit (429): {snippet}")
                if 500 <= response.status_code < 600:
                    if attempt < max_retries:
                        _t.sleep(min(2 ** attempt, 8))
                        continue
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
        # Should not reach (every path either returns or raises)
        raise AdapterError(
            self.name,
            f"exhausted retries: {last_exc}" if last_exc else "exhausted retries",
        )
