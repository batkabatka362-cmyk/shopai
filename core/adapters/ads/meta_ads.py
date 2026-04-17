"""MetaAdsAdapter — Meta (Facebook/Instagram) Marketing API.

Meta Ads covers Facebook, Instagram, Messenger, and Audience
Network advertising. This adapter wraps the Marketing API v21.0
for:

  * **Performance** — fetch campaign insights (reach, impressions,
    spend, conversions)
  * **Campaigns** — create new campaigns
  * **Budget** — update daily/lifetime budget

Authentication: long-lived access token + ad account ID.

Free tier: None (pay-per-impression/click).
Reference: https://developers.facebook.com/docs/marketing-apis
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterValidationError
from ._base import AdsBaseAdapter


_META_API_VERSION = "v21.0"


class MetaAdsAdapter(AdsBaseAdapter):
    name = "meta_ads"
    base_url = f"https://graph.facebook.com/{_META_API_VERSION}"
    config_alias = "meta_ads_access_token"

    priority = 80
    cost_per_call = 0.0

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        return bool(get_config().get("meta_ads_account_id"))

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

    def _account_id(self) -> str:
        aid = get_config().get("meta_ads_account_id")
        if not aid:
            raise AdapterValidationError(
                self.name, "META_ADS_ACCOUNT_ID not set",
            )
        # Ensure act_ prefix
        return aid if aid.startswith("act_") else f"act_{aid}"

    # ── Performance ────────────────────────────────────────────

    def _do_get_performance(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        account_id = params.get("account_id") or self._account_id()
        date_preset = params.get("date_preset", "last_30d")
        fields = params.get("fields") or (
            "campaign_name,impressions,reach,spend,"
            "clicks,actions,cost_per_action_type"
        )
        level = params.get("level", "campaign")

        url = (
            f"{self.base_url}/{account_id}/insights"
            f"?fields={fields}&date_preset={date_preset}&level={level}"
        )
        raw = self._http_request("GET", url)

        campaigns = []
        for row in raw.get("data", []):
            campaigns.append({
                "campaign_name": row.get("campaign_name", ""),
                "impressions": int(row.get("impressions", 0)),
                "reach": int(row.get("reach", 0)),
                "spend": float(row.get("spend", 0)),
                "clicks": int(row.get("clicks", 0)),
                "actions": row.get("actions", []),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"campaigns": campaigns, "date_preset": date_preset},
            raw=raw,
        )

    # ── Create campaign ────────────────────────────────────────

    def _do_create_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        if not params.get("name"):
            raise AdapterValidationError(self.name, "'name' is required")
        if not params.get("objective"):
            raise AdapterValidationError(
                self.name, "'objective' is required",
            )

        account_id = params.get("account_id") or self._account_id()
        url = f"{self.base_url}/{account_id}/campaigns"
        body = {
            "name": params["name"],
            "objective": params["objective"],
            "status": params.get("status", "PAUSED"),
            "special_ad_categories": params.get(
                "special_ad_categories", [],
            ),
        }
        if params.get("daily_budget"):
            body["daily_budget"] = params["daily_budget"]
        if params.get("lifetime_budget"):
            body["lifetime_budget"] = params["lifetime_budget"]

        raw = self._http_request("POST", url, body=body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_id": raw.get("id", ""),
                "name": params["name"],
                "status": params.get("status", "PAUSED"),
            },
            raw=raw,
        )

    # ── Update budget ──────────────────────────────────────────

    def _do_update_budget(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        if not params.get("campaign_id"):
            raise AdapterValidationError(
                self.name, "'campaign_id' is required",
            )

        campaign_id = params["campaign_id"]
        url = f"{self.base_url}/{campaign_id}"
        body: dict[str, Any] = {}
        if params.get("daily_budget"):
            body["daily_budget"] = params["daily_budget"]
        if params.get("lifetime_budget"):
            body["lifetime_budget"] = params["lifetime_budget"]

        if not body:
            raise AdapterValidationError(
                self.name,
                "at least one of 'daily_budget' or 'lifetime_budget' required",
            )

        raw = self._http_request("POST", url, body=body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_id": campaign_id,
                **body,
            },
            raw=raw,
        )

    # ── Pause campaign ────────────────────────────────────────

    def _do_pause_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        if not params.get("campaign_id"):
            raise AdapterValidationError(
                self.name, "'campaign_id' is required",
            )
        campaign_id = params["campaign_id"]
        url = f"{self.base_url}/{campaign_id}"
        body = {"status": "PAUSED"}
        raw = self._http_request("POST", url, body=body)
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"campaign_id": campaign_id, "status": "PAUSED"},
            raw=raw,
        )

    # ── Resume campaign ───────────────────────────────────────

    def _do_resume_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        if not params.get("campaign_id"):
            raise AdapterValidationError(
                self.name, "'campaign_id' is required",
            )
        campaign_id = params["campaign_id"]
        url = f"{self.base_url}/{campaign_id}"
        body = {"status": "ACTIVE"}
        raw = self._http_request("POST", url, body=body)
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"campaign_id": campaign_id, "status": "ACTIVE"},
            raw=raw,
        )
