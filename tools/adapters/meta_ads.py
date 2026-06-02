"""Meta (Facebook/Instagram) Ads adapter for ShopAI."""

import time

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class MetaAdsAdapter(BaseToolAdapter):
    tool_name = "meta_ads"
    tool_category = "ads"
    version = "1.0.0"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._ad_account_id: str = ""
        self._api_version: str = "v19.0"

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._ad_account_id = credentials.get("ad_account_id", "")
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
        healthy = bool(self._credentials.get("access_token"))
        latency = (time.monotonic() - start) * 1000 + 80.0
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=None if healthy else "No Meta access token configured",
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=4.0, burst=200, daily_quota=None)

    # ── handlers ──────────────────────────────────────────────

    def _fetch_campaigns(self, params: dict) -> dict:
        limit = params.get("limit", 25)
        status_filter = params.get("status_filter")
        fields = "id,name,status,objective,daily_budget,lifetime_budget"
        endpoint = f"/{self._api_version}/act_{self._ad_account_id}/campaigns"
        query: dict = {"fields": fields, "limit": limit}
        if status_filter:
            query["effective_status"] = [status_filter.upper()]
        return {"endpoint": endpoint, "query": query, "campaigns": []}

    def _get_campaign_status(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        cid = params["campaign_id"]
        return {
            "endpoint": f"/{self._api_version}/{cid}",
            "fields": "status,effective_status,configured_status",
            "campaign_id": cid,
            "status": "ACTIVE",
        }

    def _launch_campaign(self, params: dict) -> dict:
        required = ["name", "objective", "daily_budget"]
        missing = [f for f in required if f not in params]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        payload = {
            "name": params["name"],
            "objective": params["objective"],
            "status": "ACTIVE",
            # W962-71: round, don't truncate. int(float * 100)
            # drops sub-cent on IEEE-754 artifacts (10.99 ->
            # 1098 instead of 1099) -> systematic underbudget.
            "daily_budget": int(round(params["daily_budget"] * 100)),
            "special_ad_categories": params.get("special_ad_categories", []),
        }
        return {
            "endpoint": f"/{self._api_version}/act_{self._ad_account_id}/campaigns",
            "method": "POST",
            "payload": payload,
        }

    def _pause_campaign(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        return {
            "endpoint": f"/{self._api_version}/{params['campaign_id']}",
            "method": "POST",
            "payload": {"status": "PAUSED"},
        }

    def _resume_campaign(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        return {
            "endpoint": f"/{self._api_version}/{params['campaign_id']}",
            "method": "POST",
            "payload": {"status": "ACTIVE"},
        }

    def _update_budget(self, params: dict) -> dict:
        if "campaign_id" not in params or "daily_budget" not in params:
            raise ValueError("campaign_id and daily_budget are required")
        return {
            "endpoint": f"/{self._api_version}/{params['campaign_id']}",
            "method": "POST",
            # W962-71: round, don't truncate.
            "payload": {"daily_budget": int(round(params["daily_budget"] * 100))},
        }

    def _get_metrics(self, params: dict) -> dict:
        if "campaign_id" not in params:
            raise ValueError("campaign_id is required")
        date_range = params.get("date_range", {"since": "2024-01-01", "until": "2024-01-31"})
        fields = params.get(
            "fields",
            "impressions,clicks,spend,cpc,cpm,ctr,actions,cost_per_action_type",
        )
        return {
            "endpoint": f"/{self._api_version}/{params['campaign_id']}/insights",
            "query": {"fields": fields, "time_range": date_range},
            "metrics": {},
        }
