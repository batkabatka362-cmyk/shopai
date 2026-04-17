"""PostHogAdapter — PostHog product analytics.

PostHog is an open-source product analytics platform. Self-host
or use PostHog Cloud. Tracks events, user sessions, feature
flags, and funnel analysis.

Capabilities:
  * ANALYTICS_TRACK_EVENT — capture a custom event
  * ANALYTICS_IDENTIFY    — identify/update a user
  * ANALYTICS_QUERY       — query insights via HogQL

Auth: Project API key in request body.
Free tier: 1M events/month on PostHog Cloud.
Pricing: usage-based after free tier.

Reference: https://posthog.com/docs/api
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterValidationError
from ._base import AnalyticsBaseAdapter


class PostHogAdapter(AnalyticsBaseAdapter):
    name = "posthog"
    base_url = "https://app.posthog.com"
    config_alias = "posthog"

    priority = 85
    cost_per_call = 0.0  # free tier is generous

    def is_configured(self) -> bool:
        if not super().is_configured():
            return False
        return True

    def _get_host(self) -> str:
        return get_config().get("posthog_host") or self.base_url

    # ── Track event ──────────────────────────────��────────────

    def _do_track(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        event = params.get("event")
        if not event:
            raise AdapterValidationError(
                self.name, "'event' name is required",
            )
        distinct_id = params.get("distinct_id") or params.get("user_id")
        if not distinct_id:
            raise AdapterValidationError(
                self.name, "'distinct_id' is required",
            )

        host = self._get_host()
        url = f"{host}/capture/"
        body = {
            "api_key": self._api_key(),
            "event": event,
            "distinct_id": distinct_id,
            "properties": params.get("properties", {}),
        }
        if params.get("timestamp"):
            body["timestamp"] = params["timestamp"]

        raw = self._http_post(url, body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "event": event,
                "distinct_id": distinct_id,
                "captured": True,
            },
            raw=raw,
        )

    # ── Identify user ────────────────────────��────────────────

    def _do_identify(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        distinct_id = params.get("distinct_id") or params.get("user_id")
        if not distinct_id:
            raise AdapterValidationError(
                self.name, "'distinct_id' is required",
            )

        host = self._get_host()
        url = f"{host}/capture/"
        body = {
            "api_key": self._api_key(),
            "event": "$identify",
            "distinct_id": distinct_id,
            "$set": params.get("properties", {}),
        }

        raw = self._http_post(url, body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "distinct_id": distinct_id,
                "identified": True,
            },
            raw=raw,
        )

    # ── Query (HogQL) ──────────────────────────���─────────────

    def _do_query(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        query = params.get("query")
        if not query:
            raise AdapterValidationError(
                self.name, "'query' is required (HogQL expression)",
            )

        host = self._get_host()
        url = f"{host}/api/projects/@current/query/"
        body = {"query": {"kind": "HogQLQuery", "query": query}}
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

        raw = self._http_post(url, body, headers=headers)

        results = raw.get("results", []) if isinstance(raw, dict) else []
        columns = raw.get("columns", []) if isinstance(raw, dict) else []

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "results": results,
                "columns": columns,
                "count": len(results),
            },
            raw=raw,
        )
