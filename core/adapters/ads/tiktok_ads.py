"""TikTokAdsAdapter — TikTok (for Business) Marketing API.

TikTok Ads Manager exposes the same capability set as Meta
(campaign / budget / status / insights) through the Business
API v1.3. This adapter is the symmetric counterpart to
MetaAdsAdapter — engines that choose channels can route to
either without branching on vendor-specific request shapes.

Auth: single long-lived ``Access-Token`` header obtained from
the TikTok for Business developer portal. Combined with an
advertiser id (which we store in config rather than pass per
call so the smart-router doesn't need to know the advertiser
hierarchy).

Endpoint conventions (TikTok Business API v1.3):

  * Base: ``https://business-api.tiktok.com/open_api/v1.3``
  * Auth header: ``Access-Token: <token>``
  * Every request includes ``advertiser_id`` either in the
    body (POST) or the query string (GET).
  * Responses are enveloped: ``{"code": 0, "message": "OK",
    "data": {...}}``. ``code != 0`` means logical failure
    (quota, invalid id, etc.) even at HTTP 200 — the base
    class's HTTP handler doesn't catch that so we unwrap in
    ``_api_request`` and raise AdapterError.

Why TikTok (vs staying Meta-only):

  * Cheaper CPM on younger audiences — relevant to
    Deguar's Calm & Cozy (wellness / ambient lighting) niche
    where the core demo skews 18-34.
  * Explicit TikTok Shop integration path — orders placed
    inside the TikTok app feed the same Shopify webhook
    pipeline via TikTok Shop's Shopify integration.

Priority: 75 (below Meta's default 80) — when both are
configured Meta wins ties but owner can override via router
weights.
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterError, AdapterValidationError
from ._base import AdsBaseAdapter


_DEFAULT_API_VERSION = "v1.3"


def _resolved_version() -> str:
    override = os.environ.get(
        "SHOPAI_TIKTOK_ADS_API_VERSION", "",
    ).strip()
    return override or _DEFAULT_API_VERSION


class TikTokAdsAdapter(AdsBaseAdapter):
    """TikTok Ads — same capability surface as MetaAdsAdapter."""

    name = "tiktok_ads"
    config_alias = "tiktok_ads_access_token"

    priority = 75
    timeout = 30.0

    @property
    def base_url(self) -> str:
        return (
            f"https://business-api.tiktok.com/open_api/"
            f"{_resolved_version()}"
        )

    def is_configured(self) -> bool:
        # Both the access token AND an advertiser id are required.
        if not super().is_configured():
            return False
        return bool(
            get_config().get("tiktok_ads_advertiser_id"),
        )

    def _advertiser_id(self) -> str:
        aid = get_config().get("tiktok_ads_advertiser_id")
        if not aid:
            raise AdapterValidationError(
                self.name,
                "'TIKTOK_ADS_ADVERTISER_ID' not configured",
            )
        return str(aid)

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Access-Token": self._api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Capability implementations ────────────────────────

    def _do_create_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Create a TikTok campaign in PAUSED-equivalent state
        so live money never spends without an explicit resume
        call later (§4b.G paranoid mode)."""
        name = str(params.get("name") or "").strip()
        if not name:
            raise AdapterValidationError(
                self.name, "'name' is required",
            )
        objective = str(
            params.get("objective")
            or params.get("objective_type")
            or "CONVERSIONS",
        ).upper()
        budget_mode = str(
            params.get("budget_mode") or "BUDGET_MODE_DAY",
        ).upper()
        try:
            budget = float(params.get("budget") or 0.0)
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

        body: dict[str, Any] = {
            "advertiser_id": self._advertiser_id(),
            "campaign_name": name,
            "objective_type": objective,
            "budget_mode": budget_mode,
            "budget": float(f"{budget:.2f}"),
            # Always create paused — owner / brain must flip
            # status to ENABLE explicitly via resume_campaign.
            "operation_status": "DISABLE",
        }
        if params.get("campaign_type"):
            body["campaign_type"] = str(params["campaign_type"])

        raw = self._api_request(
            "POST", "/campaign/create/", body=body,
        )
        cid = (
            (raw.get("data") or {}).get("campaign_id")
            or (raw.get("data") or {}).get("campaign_ids") or ""
        )
        if isinstance(cid, list):
            cid = cid[0] if cid else ""
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_id": str(cid),
                "name": name,
                "objective": objective,
                "budget": body["budget"],
                "budget_mode": budget_mode,
                "status": "DISABLE",
            },
            raw=raw,
        )

    def _do_update_budget(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        cid = str(params.get("campaign_id") or "").strip()
        if not cid:
            raise AdapterValidationError(
                self.name, "'campaign_id' is required",
            )
        try:
            budget = float(params.get("budget") or 0.0)
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
        body = {
            "advertiser_id": self._advertiser_id(),
            "campaign_id": cid,
            "budget": float(f"{budget:.2f}"),
        }
        raw = self._api_request(
            "POST", "/campaign/update/", body=body,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_id": cid,
                "budget": body["budget"],
            },
            raw=raw,
        )

    def _do_pause_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        return self._set_status(
            capability, params, operation="DISABLE",
        )

    def _do_resume_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        return self._set_status(
            capability, params, operation="ENABLE",
        )

    def _set_status(
        self,
        capability: Capability,
        params: dict[str, Any],
        *,
        operation: str,
    ) -> AdapterResult:
        cid = str(params.get("campaign_id") or "").strip()
        if not cid:
            raise AdapterValidationError(
                self.name, "'campaign_id' is required",
            )
        body = {
            "advertiser_id": self._advertiser_id(),
            "campaign_ids": [cid],
            "operation_status": operation,
        }
        raw = self._api_request(
            "POST", "/campaign/status/update/", body=body,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_id": cid,
                "status": operation,
            },
            raw=raw,
        )

    def _do_get_performance(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        cid = str(params.get("campaign_id") or "").strip()
        if not cid:
            raise AdapterValidationError(
                self.name, "'campaign_id' is required",
            )
        start = str(params.get("start_date") or "").strip()
        end = str(params.get("end_date") or "").strip()
        if not start or not end:
            raise AdapterValidationError(
                self.name,
                "'start_date' + 'end_date' required "
                "(YYYY-MM-DD)",
            )
        query = {
            "advertiser_id": self._advertiser_id(),
            "report_type": "BASIC",
            "data_level": "AUCTION_CAMPAIGN",
            "dimensions": '["campaign_id"]',
            "metrics": (
                '["spend","impressions","clicks","ctr",'
                '"conversion","cost_per_conversion","cpc"]'
            ),
            "start_date": start,
            "end_date": end,
            "filtering": (
                '[{"field_name":"campaign_id",'
                '"filter_type":"IN","filter_value":'
                f'"[\\"{cid}\\"]"}}]'
            ),
        }
        raw = self._api_request(
            "GET", "/report/integrated/get/", params=query,
        )
        rows = (raw.get("data") or {}).get("list") or []
        metrics: dict[str, Any] = {}
        if rows and isinstance(rows[0], dict):
            m = rows[0].get("metrics") or {}
            for key in (
                "spend", "impressions", "clicks", "ctr",
                "conversion", "cost_per_conversion", "cpc",
            ):
                metrics[key] = m.get(key) or 0
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_id": cid,
                "start_date": start,
                "end_date": end,
                "metrics": metrics,
            },
            raw=raw,
        )

    # ── Low-level HTTP ────────────────────────────────────

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST / GET under base_url + path. Unwraps TikTok's
        envelope — logical failures (``code != 0``) raise
        AdapterError even at HTTP 200. Query params are baked
        into the URL since the base's ``_http_request`` is
        body-only."""
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
                f"TikTok returned non-dict: "
                f"{type(raw).__name__}",
            )
        code = raw.get("code", 0)
        if code and code != 0:
            message = str(
                raw.get("message") or "unknown",
            )[:200]
            raise AdapterError(
                self.name,
                f"TikTok logical failure (code={code}): "
                f"{message}",
            )
        return raw

    def _attach_idempotency_key(
        self,
        body: dict[str, Any],
        key: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """TikTok rejects unknown body fields with
        ``40002 parameter error``. Route the idempotency key
        through a custom header instead of the body."""
        headers["Request-Id"] = key
        return body
