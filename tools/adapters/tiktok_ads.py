"""TikTok Ads adapter for ShopAI."""

import time

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class TikTokAdsAdapter(BaseToolAdapter):
    tool_name = "tiktok_ads"
    tool_category = "ads"
    version = "1.0.0"

    BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._advertiser_id: str = ""

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._advertiser_id = credentials.get("advertiser_id", "")

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
        healthy = bool(self._credentials.get("access_token"))
        latency = (time.monotonic() - start) * 1000 + 120.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "No TikTok access token configured",
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=10.0, burst=50, daily_quota=None)

    # ── handlers ──────────────────────────────────────────────

    def _fetch_campaigns(self, params: dict) -> dict:
        page = params.get("page", 1)
        page_size = params.get("page_size", 20)
        filtering = {}
        if "status" in params:
            filtering["primary_status"] = params["status"]
        return {
            "endpoint": f"{self.BASE_URL}/campaign/get/",
            "method": "GET",
            "query": {
                "advertiser_id": self._advertiser_id,
                "page": page,
                "page_size": page_size,
                "filtering": filtering,
            },
            "campaigns": [],
        }

    def _get_campaign_status(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        return {
            "endpoint": f"{self.BASE_URL}/campaign/get/",
            "query": {
                "advertiser_id": self._advertiser_id,
                "filtering": {"campaign_ids": [params["campaign_id"]]},
            },
            "campaign_id": params["campaign_id"],
            "status": "CAMPAIGN_STATUS_ENABLE",
        }

    def _launch_campaign(self, params: dict) -> dict:
        required = ["campaign_name", "objective_type", "budget"]
        missing = [f for f in required if f not in params]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        payload = {
            "advertiser_id": self._advertiser_id,
            "campaign_name": params["campaign_name"],
            "objective_type": params["objective_type"],
            "budget_mode": params.get("budget_mode", "BUDGET_MODE_DAY"),
            "budget": params["budget"],
            "operation_status": "ENABLE",
        }
        return {
            "endpoint": f"{self.BASE_URL}/campaign/create/",
            "method": "POST",
            "payload": payload,
        }

    def _pause_campaign(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        return {
            "endpoint": f"{self.BASE_URL}/campaign/status/update/",
            "method": "POST",
            "payload": {
                "advertiser_id": self._advertiser_id,
                "campaign_ids": [params["campaign_id"]],
                "opt_status": "DISABLE",
            },
        }

    def _resume_campaign(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        return {
            "endpoint": f"{self.BASE_URL}/campaign/status/update/",
            "method": "POST",
            "payload": {
                "advertiser_id": self._advertiser_id,
                "campaign_ids": [params["campaign_id"]],
                "opt_status": "ENABLE",
            },
        }

    def _update_budget(self, params: dict) -> dict:
        if "campaign_id" not in params or "budget" not in params:
            raise ValueError("campaign_id and budget are required")
        return {
            "endpoint": f"{self.BASE_URL}/campaign/update/",
            "method": "POST",
            "payload": {
                "advertiser_id": self._advertiser_id,
                "campaign_id": params["campaign_id"],
                "budget": params["budget"],
                "budget_mode": params.get("budget_mode", "BUDGET_MODE_DAY"),
            },
        }

    def _get_metrics(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        start_date = params.get("start_date", "2024-01-01")
        end_date = params.get("end_date", "2024-01-31")
        metrics = params.get(
            "metrics",
            ["spend", "impressions", "clicks", "cpc", "cpm", "ctr", "conversion", "cost_per_conversion"],
        )
        return {
            "endpoint": f"{self.BASE_URL}/report/integrated/get/",
            "method": "GET",
            "query": {
                "advertiser_id": self._advertiser_id,
                "report_type": "BASIC",
                "dimensions": ["campaign_id"],
                "metrics": metrics,
                "start_date": start_date,
                "end_date": end_date,
                "filtering": [{"field_name": "campaign_ids", "filter_type": "IN", "filter_value": [params["campaign_id"]]}],
            },
            "metrics": {},
        }
