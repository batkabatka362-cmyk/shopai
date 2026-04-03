"""Analytics adapter for ShopAI — supports GA4 and Mixpanel."""

import time

from tools.base import (
    BaseToolAdapter,
    HealthStatus,
    RateConfig,
    ToolMetadata,
    ToolResult,
)


class AnalyticsAdapter(BaseToolAdapter):
    tool_name = "analytics"
    tool_category = "analytics"
    version = "1.0.0"

    def __init__(self) -> None:
        self._credentials: dict = {}
        self._ga4_property_id: str = ""
        self._mixpanel_project_id: str = ""

    def configure(self, credentials: dict) -> None:
        self._credentials = credentials
        self._ga4_property_id = credentials.get("ga4_property_id", "")
        self._mixpanel_project_id = credentials.get("mixpanel_project_id", "")

    def capabilities(self) -> list[str]:
        return [
            "fetch_ga4_report",
            "fetch_mixpanel_events",
            "fetch_combined_dashboard",
        ]

    def execute(self, action: str, params: dict) -> ToolResult:
        dispatch = {
            "fetch_ga4_report": self._fetch_ga4_report,
            "fetch_mixpanel_events": self._fetch_mixpanel_events,
            "fetch_combined_dashboard": self._fetch_combined_dashboard,
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
        ga4_ok = bool(self._credentials.get("ga4_credentials"))
        mixpanel_ok = bool(self._credentials.get("mixpanel_api_secret"))
        healthy = ga4_ok or mixpanel_ok
        latency = (time.monotonic() - start) * 1000 + 55.0
        errors = []
        if not ga4_ok:
            errors.append("GA4 credentials missing")
        if not mixpanel_ok:
            errors.append("Mixpanel API secret missing")
        return HealthStatus(
            healthy=healthy,
            latency_ms=latency,
            last_check=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error="; ".join(errors) if errors else None,
        )

    def get_rate_config(self) -> RateConfig:
        return RateConfig(requests_per_second=5.0, burst=20, daily_quota=25000)

    # ── handlers ──────────────────────────────────────────────

    def _fetch_ga4_report(self, params: dict) -> dict:
        date_from = params.get("date_from", "28daysAgo")
        date_to = params.get("date_to", "today")
        dimensions = params.get("dimensions", [{"name": "date"}])
        metrics = params.get(
            "metrics",
            [
                {"name": "sessions"},
                {"name": "totalUsers"},
                {"name": "screenPageViews"},
                {"name": "conversions"},
                {"name": "totalRevenue"},
            ],
        )
        request_body = {
            "property": f"properties/{self._ga4_property_id}",
            "dateRanges": [{"startDate": date_from, "endDate": date_to}],
            "dimensions": dimensions,
            "metrics": metrics,
            "limit": params.get("limit", 1000),
        }
        return {
            "endpoint": f"https://analyticsdata.googleapis.com/v1beta/properties/{self._ga4_property_id}:runReport",
            "method": "POST",
            "payload": request_body,
            "rows": [],
        }

    def _fetch_mixpanel_events(self, params: dict) -> dict:
        event_name = params.get("event")
        if not event_name:
            raise ValueError("event name is required")
        from_date = params.get("from_date", "2024-01-01")
        to_date = params.get("to_date", "2024-01-31")
        where_clause = params.get("where")
        query: dict = {
            "event": event_name,
            "from_date": from_date,
            "to_date": to_date,
            "type": params.get("type", "general"),
        }
        if where_clause:
            query["where"] = where_clause
        return {
            "endpoint": "https://data.mixpanel.com/api/2.0/export",
            "method": "GET",
            "query": query,
            "project_id": self._mixpanel_project_id,
            "events": [],
        }

    def _fetch_combined_dashboard(self, params: dict) -> dict:
        date_from = params.get("date_from", "28daysAgo")
        date_to = params.get("date_to", "today")
        ga4_request = {
            "property": f"properties/{self._ga4_property_id}",
            "dateRanges": [{"startDate": date_from, "endDate": date_to}],
            "dimensions": [{"name": "date"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "totalUsers"},
                {"name": "totalRevenue"},
            ],
        }
        mixpanel_request = {
            "event": params.get("mixpanel_event", "page_view"),
            "from_date": date_from if date_from != "28daysAgo" else "2024-01-01",
            "to_date": date_to if date_to != "today" else "2024-01-31",
            "type": "general",
        }
        return {
            "sources": {
                "ga4": {
                    "endpoint": f"https://analyticsdata.googleapis.com/v1beta/properties/{self._ga4_property_id}:runReport",
                    "payload": ga4_request,
                },
                "mixpanel": {
                    "endpoint": "https://data.mixpanel.com/api/2.0/export",
                    "query": mixpanel_request,
                },
            },
            "combined_metrics": {},
        }
