"""GoogleAdsAdapter — Google Ads API integration.

Google Ads is the world's largest ad platform. This adapter wraps
the Google Ads REST API v17 for:

  * **Performance** — fetch campaign/ad group metrics (impressions,
    clicks, conversions, cost)
  * **Campaigns** — create new campaigns (Search, Display, Shopping)
  * **Budget** — update daily budget for existing campaigns

Authentication uses OAuth2 (client ID + secret + refresh token)
plus a developer token. The adapter handles token refresh
automatically.

Free tier: None (pay-per-click).
Reference: https://developers.google.com/google-ads/api/docs/start
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterValidationError
from ._base import AdsBaseAdapter


class GoogleAdsAdapter(AdsBaseAdapter):
    name = "google_ads"
    base_url = "https://googleads.googleapis.com/v17"
    config_alias = "google_ads_developer_token"

    priority = 85
    cost_per_call = 0.0  # API itself is free; ad spend is separate

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        cfg = get_config()
        return all([
            cfg.get("google_ads_client_id"),
            cfg.get("google_ads_client_secret"),
            cfg.get("google_ads_refresh_token"),
            cfg.get("google_ads_customer_id"),
        ])

    def _auth_headers(self) -> dict[str, str]:
        cfg = get_config()
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "developer-token": self._api_key(),
            "login-customer-id": cfg.get("google_ads_customer_id"),
            "Content-Type": "application/json",
        }

    def _get_access_token(self) -> str:
        """Exchange refresh token for an access token via Google OAuth2."""
        import requests

        cfg = get_config()
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "refresh_token",
                "client_id": cfg.get("google_ads_client_id"),
                "client_secret": cfg.get("google_ads_client_secret"),
                "refresh_token": cfg.get("google_ads_refresh_token"),
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    # ── Performance ────────────────────────────────────────────

    def _do_get_performance(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        customer_id = (
            params.get("customer_id")
            or get_config().get("google_ads_customer_id")
        )
        if not customer_id:
            raise AdapterValidationError(
                self.name, "customer_id is required",
            )

        date_range = params.get("date_range", "LAST_30_DAYS")
        query = params.get("query") or (
            "SELECT campaign.name, campaign.id, "
            "metrics.impressions, metrics.clicks, "
            "metrics.cost_micros, metrics.conversions "
            f"FROM campaign WHERE segments.date DURING {date_range}"
        )

        url = f"{self.base_url}/customers/{customer_id}/googleAds:searchStream"
        raw = self._http_request("POST", url, body={"query": query})

        results = []
        for batch in raw if isinstance(raw, list) else [raw]:
            for row in batch.get("results", []):
                campaign = row.get("campaign", {})
                metrics = row.get("metrics", {})
                results.append({
                    "campaign_name": campaign.get("name", ""),
                    "campaign_id": campaign.get("id", ""),
                    "impressions": int(metrics.get("impressions", 0)),
                    "clicks": int(metrics.get("clicks", 0)),
                    "cost": int(metrics.get("costMicros", 0)) / 1_000_000,
                    "conversions": float(metrics.get("conversions", 0)),
                })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"campaigns": results, "date_range": date_range},
            raw=raw,
        )

    # ── Create campaign ────────────────────────────────────────

    def _do_create_campaign(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        if not params.get("name"):
            raise AdapterValidationError(self.name, "'name' is required")
        if not params.get("budget_amount_micros"):
            raise AdapterValidationError(
                self.name, "'budget_amount_micros' is required",
            )

        customer_id = (
            params.get("customer_id")
            or get_config().get("google_ads_customer_id")
        )
        url = f"{self.base_url}/customers/{customer_id}/campaigns:mutate"
        body = {
            "operations": [{
                "create": {
                    "name": params["name"],
                    "advertisingChannelType": params.get(
                        "channel_type", "SEARCH",
                    ),
                    "status": params.get("status", "PAUSED"),
                    "campaignBudget": {
                        "amountMicros": params["budget_amount_micros"],
                        "deliveryMethod": "STANDARD",
                    },
                },
            }],
        }

        raw = self._http_request("POST", url, body=body)
        campaign_id = ""
        results = raw.get("results", [])
        if results:
            campaign_id = results[0].get("resourceName", "")

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_id": campaign_id,
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
        if "budget_amount_micros" not in params:
            raise AdapterValidationError(
                self.name, "'budget_amount_micros' is required",
            )

        customer_id = (
            params.get("customer_id")
            or get_config().get("google_ads_customer_id")
        )
        url = f"{self.base_url}/customers/{customer_id}/campaignBudgets:mutate"
        body = {
            "operations": [{
                "update": {
                    "resourceName": params["campaign_id"],
                    "amountMicros": params["budget_amount_micros"],
                },
                "updateMask": "amountMicros",
            }],
        }

        raw = self._http_request("POST", url, body=body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "campaign_id": params["campaign_id"],
                "budget_micros": params["budget_amount_micros"],
            },
            raw=raw,
        )
