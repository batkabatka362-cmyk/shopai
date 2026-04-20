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

import os
import time
import uuid
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


# Retry configuration — can be overridden per subclass if a vendor
# has different limits.
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BACKOFF_BASE_S = 0.5


def _brain_hooks_on() -> bool:
    return os.getenv("SHOPAI_BRAIN_HOOKS", "") == "1"


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

    # Capabilities that should trigger an outcome_recorder hook on
    # success. Reads (GET_PERFORMANCE) are skipped.
    _BRAIN_HOOK_CAPABILITIES: set[Capability] = {
        Capability.ADS_CREATE_CAMPAIGN,
        Capability.ADS_UPDATE_BUDGET,
        Capability.ADS_PAUSE_CAMPAIGN,
        Capability.ADS_RESUME_CAMPAIGN,
    }

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
        result = handler(capability, params)
        if (
            capability in self._BRAIN_HOOK_CAPABILITIES
            and _brain_hooks_on()
        ):
            self._notify_brain_on_write(capability, params, result)
        return result

    def _notify_brain_on_write(
        self,
        capability: Capability,
        params: dict[str, Any],
        result: AdapterResult,
    ) -> None:
        """Feed each successful ad-platform write into the brain
        learner stack. Caller can attach decision_id +
        claimed_confidence via params for calibration tracking."""
        try:
            from core.attribution.outcome_recorder import (
                OutcomeEvent, OutcomeRecorder,
            )
            OutcomeRecorder().record(OutcomeEvent(
                kind="ad_action",
                ok=bool(result.success),
                decision_id=str(
                    params.get("decision_id") or "",
                ),
                claimed_confidence=float(
                    params.get("claimed_confidence") or 0.0,
                ),
                capability_name=f"ads:{capability.value}",
                kpi=capability.value,
                kpi_value=1.0 if result.success else 0.0,
                signals=tuple(params.get("signals") or ()),
                note=f"{self.name}:{capability.value}",
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "brain notify (%s %s) skipped: %s",
                self.name, capability.value, exc,
            )

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

    # Overridable per subclass. Tests patch to 0 to avoid waits.
    max_retries: int = _DEFAULT_MAX_RETRIES
    backoff_base_s: float = _DEFAULT_BACKOFF_BASE_S

    def _http_request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """HTTP request with exponential backoff on 429 / 5xx.

        ``idempotency_key`` (if not supplied on writes) is
        auto-generated so a retried POST never creates a duplicate
        resource. Meta's Graph API ignores unknown fields, so the
        key is harmlessly attached to the body as
        ``_client_request_id`` for write verbs. Subclasses can
        override ``_attach_idempotency_key`` to wire it to a
        vendor-specific header.
        """
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        hdrs = headers or self._auth_headers()
        write = method.upper() != "GET"
        if write and idempotency_key is None:
            idempotency_key = f"req_{uuid.uuid4().hex}"
        effective_body = dict(body or {}) if write else None
        if write and idempotency_key and effective_body is not None:
            effective_body = self._attach_idempotency_key(
                dict(effective_body), idempotency_key, hdrs,
            )
        max_attempts = max(1, int(self.max_retries) + 1)
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return self._do_http_once(
                    method=method, url=url,
                    body=effective_body, headers=hdrs,
                )
            except (
                AdapterRateLimited, AdapterUnavailable, AdapterTimeout,
            ) as exc:
                last_exc = exc
                # Only retry on transient errors
                if attempt + 1 >= max_attempts:
                    break
                sleep_s = self.backoff_base_s * (2 ** attempt)
                logger.warning(
                    "%s retry %d/%d after %s: %s",
                    self.name, attempt + 1, max_attempts - 1,
                    type(exc).__name__, exc,
                )
                time.sleep(sleep_s)
        # Exhausted retries — re-raise the last transient error
        assert last_exc is not None  # for type checker
        raise last_exc

    def _attach_idempotency_key(
        self,
        body: dict[str, Any],
        key: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Default: body-field attachment. Subclasses can override
        to push the key into a vendor-specific header instead."""
        body.setdefault("_client_request_id", key)
        return body

    def _do_http_once(
        self,
        *,
        method: str,
        url: str,
        body: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> Any:
        try:
            if method.upper() == "GET":
                response = _requests.get(url, headers=headers, timeout=self.timeout)
            else:
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
