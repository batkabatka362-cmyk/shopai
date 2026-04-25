"""GoogleAdsAdapter — Google Ads REST API v18.

Third ad-platform adapter after Meta + TikTok. Closes the
ad-triad so engines picking a channel can route to any of
the three without branching on vendor specifics.

Google Ads is the most complex of the three:

  * Auth: OAuth2 refresh token exchanged for a short-lived
    access token on every session. Plus a separate
    ``developer-token`` header (approved by Google's
    developer portal, not per-customer).
  * Resource model: budgets live separately from campaigns —
    to create a campaign you first create a
    campaignBudget, then reference its resource_name in the
    campaign's ``campaign_budget`` field. This adapter
    bundles the two-step dance into a single
    ``create_campaign`` call.
  * Updates use field_mask to declare which fields are being
    changed — passing ``amount_micros`` without a mask is a
    silent no-op on Google's side.
  * Money uses MICRO units: $25.50 → 25_500_000 micros.
    Helpers below translate cleanly.
  * Performance queries go through GoogleAdsService.search
    with a GAQL SQL-ish string.

Paranoid mode (§4b.G): campaigns are always created with
status=PAUSED. Resume requires an explicit
ADS_RESUME_CAMPAIGN call.

Priority: 70 (below Meta 80, below TikTok 75) — Google
covers SERP + YouTube which is owner-requested on some
campaigns but not the default placement.
"""
from __future__ import annotations

import os
import threading
import time
import urllib.parse
from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterValidationError,
)
from ._base import AdsBaseAdapter, _REQUESTS_AVAILABLE, _requests


_DEFAULT_API_VERSION = "v18"
# $1 = 1_000_000 micros.
_MICRO_PER_UNIT = 1_000_000
# Refresh the bearer token this many seconds before its
# declared expiry so an in-flight call never trips on an
# expired header.
_TOKEN_REFRESH_LEAD_S = 60.0


def _resolved_version() -> str:
    override = os.environ.get(
        "SHOPAI_GOOGLE_ADS_API_VERSION", "",
    ).strip()
    return override or _DEFAULT_API_VERSION


def _usd_to_micros(value: float | int | str) -> int:
    try:
        amt = float(value)
    except (TypeError, ValueError) as exc:
        raise AdapterValidationError(
            "google_ads",
            f"numeric value expected (got {value!r})",
        ) from exc
    return int(round(amt * _MICRO_PER_UNIT))


class GoogleAdsAdapter(AdsBaseAdapter):
    """Google Ads REST adapter — mirrors the Capability
    surface of Meta + TikTok."""

    name = "google_ads"
    # Primary credential the base's is_configured() reads.
    config_alias = "google_ads_developer_token"

    priority = 70
    timeout = 30.0

    def __init__(self) -> None:
        super().__init__()
        self._token_lock = threading.Lock()
        self._cached_access_token: str = ""
        self._token_expires_at: float = 0.0

    # ── Configuration ─────────────────────────────────

    @property
    def base_url(self) -> str:
        return (
            f"https://googleads.googleapis.com/"
            f"{_resolved_version()}"
        )

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        cfg = get_config()
        for key in (
            "google_ads_developer_token",
            "google_ads_client_id",
            "google_ads_client_secret",
            "google_ads_refresh_token",
            "google_ads_customer_id",
        ):
            if not cfg.get(key):
                return False
        return True

    def _customer_id(self) -> str:
        cid = get_config().get("google_ads_customer_id")
        if not cid:
            raise AdapterNotConfigured(
                self.name,
                "'GOOGLE_ADS_CUSTOMER_ID' not configured",
            )
        # Google's customer ids are typically dash-formatted
        # ("123-456-7890"); the REST path expects digits only.
        return str(cid).replace("-", "")

    # ── OAuth2 access token ──────────────────────────

    def _access_token(self) -> str:
        now = time.monotonic()
        if (
            self._cached_access_token
            and now < self._token_expires_at - _TOKEN_REFRESH_LEAD_S
        ):
            return self._cached_access_token
        with self._token_lock:
            now = time.monotonic()
            if (
                self._cached_access_token
                and now < self._token_expires_at
                - _TOKEN_REFRESH_LEAD_S
            ):
                return self._cached_access_token
            token, expires_in = self._refresh_token()
            self._cached_access_token = token
            self._token_expires_at = (
                time.monotonic() + max(expires_in, 0.0)
            )
            return self._cached_access_token

    def _refresh_token(self) -> tuple[str, float]:
        cfg = get_config()
        client_id = cfg.get("google_ads_client_id")
        client_secret = cfg.get("google_ads_client_secret")
        refresh = cfg.get("google_ads_refresh_token")
        if not (client_id and client_secret and refresh):
            raise AdapterNotConfigured(
                self.name,
                "missing OAuth2 credentials — set "
                "GOOGLE_ADS_CLIENT_ID + "
                "GOOGLE_ADS_CLIENT_SECRET + "
                "GOOGLE_ADS_REFRESH_TOKEN",
            )
        if not _REQUESTS_AVAILABLE:
            raise AdapterError(
                self.name, "'requests' not installed",
            )
        try:
            resp = _requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                },
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"oauth2 refresh failed: "
                f"{type(exc).__name__}: {exc}",
            ) from exc
        status = getattr(resp, "status_code", 0)
        if status in (401, 403):
            raise AdapterAuthError(
                self.name,
                f"oauth2 rejected credentials ({status})",
            )
        if status >= 400:
            snippet = (
                getattr(resp, "text", "") or ""
            )[:200]
            raise AdapterError(
                self.name,
                f"oauth2 returned {status}: {snippet}",
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise AdapterError(
                self.name,
                f"oauth2 non-JSON body: {exc}",
            ) from exc
        token = (
            payload.get("access_token", "")
            if isinstance(payload, dict) else ""
        )
        if not token:
            raise AdapterError(
                self.name,
                "oauth2 response missing access_token",
            )
        expires_in = float(
            payload.get("expires_in", 0) or 0,
        )
        return str(token), expires_in

    def _auth_headers(self) -> dict[str, str]:
        cfg = get_config()
        return {
            "Authorization":
                f"Bearer {self._access_token()}",
            "developer-token": str(
                cfg.get("google_ads_developer_token"),
            ),
            "login-customer-id": self._customer_id(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Capabilities ─────────────────────────────────

    def _do_create_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Create a PAUSED campaign. Two-step: budget +
        campaign. Returns the campaign resource_name."""
        name = str(params.get("name") or "").strip()
        if not name:
            raise AdapterValidationError(
                self.name, "'name' is required",
            )
        try:
            budget = float(params.get("budget") or 0)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                f"'budget' must be numeric "
                f"(got {params.get('budget')!r})",
            ) from exc
        if budget <= 0:
            raise AdapterValidationError(
                self.name, "'budget' must be > 0",
            )
        channel = str(
            params.get("advertising_channel_type")
            or "SEARCH",
        ).upper()

        # 1) Create budget.
        budget_micros = _usd_to_micros(budget)
        budget_payload = {
            "operations": [{
                "create": {
                    "name": f"budget for {name}",
                    "amount_micros": str(budget_micros),
                    "delivery_method": "STANDARD",
                },
            }],
        }
        budget_resp = self._api_request(
            "POST",
            f"/customers/{self._customer_id()}/"
            "campaignBudgets:mutate",
            body=budget_payload,
        )
        budget_resource = ""
        try:
            budget_resource = (
                budget_resp.get("results") or [{}]
            )[0].get("resourceName") or ""
        except AttributeError:
            budget_resource = ""
        if not budget_resource:
            raise AdapterError(
                self.name,
                "campaignBudgets:mutate returned no "
                "resourceName",
            )

        # 2) Create campaign referencing the budget; PAUSED.
        campaign_payload = {
            "operations": [{
                "create": {
                    "name": name,
                    "advertising_channel_type": channel,
                    "status": "PAUSED",
                    "campaign_budget": budget_resource,
                    # Bidding strategy required by API.
                    "manual_cpc": {
                        "enhanced_cpc_enabled": False,
                    },
                },
            }],
        }
        campaign_resp = self._api_request(
            "POST",
            f"/customers/{self._customer_id()}/"
            "campaigns:mutate",
            body=campaign_payload,
        )
        try:
            campaign_resource = (
                campaign_resp.get("results") or [{}]
            )[0].get("resourceName") or ""
        except AttributeError:
            campaign_resource = ""
        if not campaign_resource:
            raise AdapterError(
                self.name,
                "campaigns:mutate returned no resourceName",
            )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_resource": campaign_resource,
                "campaign_id": campaign_resource.split("/")[
                    -1
                ],
                "budget_resource": budget_resource,
                "budget_micros": budget_micros,
                "status": "PAUSED",
                "name": name,
            },
            raw=campaign_resp,
        )

    def _do_update_budget(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        resource = str(
            params.get("budget_resource") or "",
        ).strip()
        if not resource:
            raise AdapterValidationError(
                self.name,
                "'budget_resource' is required (e.g. "
                "'customers/{cid}/campaignBudgets/{id}')",
            )
        try:
            budget = float(params.get("budget") or 0)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                f"'budget' must be numeric "
                f"(got {params.get('budget')!r})",
            ) from exc
        if budget <= 0:
            raise AdapterValidationError(
                self.name, "'budget' must be > 0",
            )
        budget_micros = _usd_to_micros(budget)
        body = {
            "operations": [{
                "update": {
                    "resourceName": resource,
                    "amount_micros": str(budget_micros),
                },
                "updateMask": "amount_micros",
            }],
        }
        raw = self._api_request(
            "POST",
            f"/customers/{self._customer_id()}/"
            "campaignBudgets:mutate",
            body=body,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "budget_resource": resource,
                "budget_micros": budget_micros,
            },
            raw=raw,
        )

    def _do_pause_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        return self._set_campaign_status(
            capability, params, status="PAUSED",
        )

    def _do_resume_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        return self._set_campaign_status(
            capability, params, status="ENABLED",
        )

    def _set_campaign_status(
        self,
        capability: Capability,
        params: dict[str, Any],
        *,
        status: str,
    ) -> AdapterResult:
        resource = str(
            params.get("campaign_resource") or "",
        ).strip()
        if not resource:
            raise AdapterValidationError(
                self.name,
                "'campaign_resource' is required",
            )
        body = {
            "operations": [{
                "update": {
                    "resourceName": resource,
                    "status": status,
                },
                "updateMask": "status",
            }],
        }
        raw = self._api_request(
            "POST",
            f"/customers/{self._customer_id()}/"
            "campaigns:mutate",
            body=body,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_resource": resource,
                "status": status,
            },
            raw=raw,
        )

    def _do_get_performance(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        resource = str(
            params.get("campaign_resource") or "",
        ).strip()
        if not resource:
            raise AdapterValidationError(
                self.name,
                "'campaign_resource' is required",
            )
        start = str(params.get("start_date") or "").strip()
        end = str(params.get("end_date") or "").strip()
        if not start or not end:
            raise AdapterValidationError(
                self.name,
                "'start_date' + 'end_date' required "
                "(YYYY-MM-DD)",
            )
        # GAQL expects dashed date strings inline.
        gaql = (
            "SELECT metrics.impressions, metrics.clicks, "
            "metrics.ctr, metrics.cost_micros, "
            "metrics.conversions "
            "FROM campaign "
            f"WHERE campaign.resource_name = '{resource}' "
            f"AND segments.date BETWEEN '{start}' AND '{end}'"
        )
        raw = self._api_request(
            "POST",
            f"/customers/{self._customer_id()}/"
            "googleAds:search",
            body={"query": gaql},
        )
        rows = raw.get("results") or []
        metrics: dict[str, Any] = {
            "impressions": 0, "clicks": 0, "ctr": 0.0,
            "cost_usd": 0.0, "conversions": 0,
        }
        if rows and isinstance(rows[0], dict):
            m = rows[0].get("metrics") or {}
            metrics["impressions"] = int(
                m.get("impressions") or 0,
            )
            metrics["clicks"] = int(m.get("clicks") or 0)
            try:
                metrics["ctr"] = float(m.get("ctr") or 0)
            except (TypeError, ValueError):
                metrics["ctr"] = 0.0
            try:
                metrics["cost_usd"] = round(
                    float(
                        m.get("cost_micros") or 0,
                    ) / _MICRO_PER_UNIT,
                    2,
                )
            except (TypeError, ValueError):
                metrics["cost_usd"] = 0.0
            try:
                metrics["conversions"] = int(
                    float(m.get("conversions") or 0),
                )
            except (TypeError, ValueError):
                metrics["conversions"] = 0
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_resource": resource,
                "start_date": start,
                "end_date": end,
                "metrics": metrics,
            },
            raw=raw,
        )

    # ── Low-level HTTP ────────────────────────────────

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            qs = urllib.parse.urlencode(
                {k: str(v) for k, v in params.items()},
            )
            url = f"{url}?{qs}"
        raw = self._http_request(method, url, body=body)
        if not isinstance(raw, dict):
            raise AdapterError(
                self.name,
                f"Google Ads returned non-dict: "
                f"{type(raw).__name__}",
            )
        return raw

    def _attach_idempotency_key(
        self,
        body: dict[str, Any],
        key: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Google Ads rejects unknown body fields. Route the
        idempotency key through a request header instead."""
        headers["x-goog-request-id"] = key
        return body
