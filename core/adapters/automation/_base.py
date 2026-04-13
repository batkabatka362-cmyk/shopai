"""AutomationBaseAdapter — shared base for automation adapters.

Concrete adapters (Zapier today; Make/n8n later) inherit this
class and override vendor-specific hooks.

Capabilities:
  * AUTOMATION_TRIGGER   — trigger a workflow/zap/scenario
  * AUTOMATION_LIST_ZAPS — list available automations
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

logger = get_logger("adapters.automation")


class AutomationBaseAdapter(BaseAdapter):
    """Abstract base for workflow automation adapters."""

    category = AdapterCategory.AUTOMATION
    capabilities = {
        Capability.AUTOMATION_TRIGGER,
        Capability.AUTOMATION_LIST_ZAPS,
    }

    base_url: str = ""
    config_alias: str = ""
    timeout: float = 30.0
    cost_per_call: float = 0.0

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

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        dispatch = {
            Capability.AUTOMATION_TRIGGER: self._do_trigger,
            Capability.AUTOMATION_LIST_ZAPS: self._do_list_zaps,
        }
        handler = dispatch.get(capability)
        if handler is None:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )
        return handler(capability, params)

    # ── Vendor hooks ───────────────────────────────────────────

    def _do_trigger(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError

    def _do_list_zaps(
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
                self.name, f"timeout after {self.timeout}s",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            raise AdapterUnavailable(
                self.name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name, f"HTTP {method} failed: {exc}",
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
