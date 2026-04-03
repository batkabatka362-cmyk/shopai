"""Google Ads adapter for ShopAI."""

import time

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class GoogleAdsAdapter(BaseToolAdapter):
    tool_name = "google_ads"
    tool_category = "ads"
    version = "1.0.0"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._customer_id: str = ""
        self._api_version: str = "v16"

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._customer_id = credentials.get("customer_id", "").replace("-", "")
        self._api_version = credentials.get("api_version", self._api_version)

    def capabilities(self) -> list[str]:
        return [
            "fetch_campaigns",
            "get_campaign_status",
            "launch_campaign",
            "pause_campaign",
            "resume_campaign",
            "update_budget",
            "get_metrics",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "fetch_campaigns": self._fetch_campaigns,
            "get_campaign_status": self._get_campaign_status,
            "launch_campaign": self._launch_campaign,
            "pause_campaign": self._pause_campaign,
            "resume_campaign": self._resume_campaign,
            "update_budget": self._update_budget,
            "get_metrics": self._get_metrics,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, data={}, error=f"Unknown action: {action}")
        start = time.monotonic()
        try:
            result = handler(params)
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=True,
                data=result,
                error=None,
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                success=False,
                data={},
                error=str(exc),
                metadata=ToolMetadata(
                    duration_ms=elapsed,
                    attempt_count=1,
                    rate_limited=False,
                    cost_usd=0.0,
                    tool_name=self.tool_name,
                    action=action,
                ),
            )

    def health_check(self) -> HealthStatus:
        start = time.monotonic()
        healthy = bool(self._credentials.get("developer_token"))
        latency = (time.monotonic() - start) * 1000 + 60.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "No developer token configured",
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=10.0, burst=100, daily_quota=15000)

    # ── handlers ──────────────────────────────────────────────

    def _fetch_campaigns(self, params: dict) -> dict:
        limit = params.get("limit", 50)
        gaql = (
            "SELECT campaign.id, campaign.name, campaign.status, "
            "campaign.advertising_channel_type, campaign_budget.amount_micros "
            f"FROM campaign ORDER BY campaign.id LIMIT {limit}"
        )
        return {
            "service": "GoogleAdsService",
            "method": "SearchStream",
            "customer_id": self._customer_id,
            "query": gaql,
            "campaigns": [],
        }

    def _get_campaign_status(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        gaql = (
            "SELECT campaign.id, campaign.status, campaign.serving_status "
            f"FROM campaign WHERE campaign.id = {params['campaign_id']}"
        )
        return {
            "service": "GoogleAdsService",
            "method": "Search",
            "query": gaql,
            "campaign_id": params["campaign_id"],
            "status": "ENABLED",
        }

    def _launch_campaign(self, params: dict) -> dict:
        required = ["name", "channel_type", "budget_amount_micros"]
        missing = [f for f in required if f not in params]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        budget_op = {
            "create": {
                "name": f"{params['name']}_budget",
                "amount_micros": params["budget_amount_micros"],
                "delivery_method": "STANDARD",
            }
        }
        campaign_op = {
            "create": {
                "name": params["name"],
                "advertising_channel_type": params["channel_type"],
                "status": "ENABLED",
                "campaign_budget": "pending_budget_resource",
                "bidding_strategy_type": params.get("bidding_strategy", "MAXIMIZE_CONVERSIONS"),
            }
        }
        return {
            "service": "CampaignService",
            "method": "MutateCampaigns",
            "customer_id": self._customer_id,
            "budget_operation": budget_op,
            "campaign_operation": campaign_op,
        }

    def _pause_campaign(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        return {
            "service": "CampaignService",
            "method": "MutateCampaigns",
            "customer_id": self._customer_id,
            "operation": {
                "update": {
                    "resource_name": f"customers/{self._customer_id}/campaigns/{params['campaign_id']}",
                    "status": "PAUSED",
                },
                "update_mask": "status",
            },
        }

    def _resume_campaign(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        return {
            "service": "CampaignService",
            "method": "MutateCampaigns",
            "customer_id": self._customer_id,
            "operation": {
                "update": {
                    "resource_name": f"customers/{self._customer_id}/campaigns/{params['campaign_id']}",
                    "status": "ENABLED",
                },
                "update_mask": "status",
            },
        }

    def _update_budget(self, params: dict) -> dict:
        if "budget_id" not in params or "amount_micros" not in params:
            raise ValueError("budget_id and amount_micros are required")
        return {
            "service": "CampaignBudgetService",
            "method": "MutateCampaignBudgets",
            "customer_id": self._customer_id,
            "operation": {
                "update": {
                    "resource_name": f"customers/{self._customer_id}/campaignBudgets/{params['budget_id']}",
                    "amount_micros": params["amount_micros"],
                },
                "update_mask": "amount_micros",
            },
        }

    def _get_metrics(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        date_from = params.get("date_from", "2024-01-01")
        date_to = params.get("date_to", "2024-01-31")
        gaql = (
            "SELECT campaign.id, metrics.impressions, metrics.clicks, "
            "metrics.cost_micros, metrics.conversions, metrics.ctr, metrics.average_cpc "
            f"FROM campaign WHERE campaign.id = {params['campaign_id']} "
            f"AND segments.date BETWEEN '{date_from}' AND '{date_to}'"
        )
        return {
            "service": "GoogleAdsService",
            "method": "Search",
            "query": gaql,
            "metrics": {},
        }
