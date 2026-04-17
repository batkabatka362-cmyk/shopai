"""MixpanelAdapter — Mixpanel user behavior analytics.

Mixpanel tracks user interactions with web and mobile apps.
Strong in funnel analysis, retention, and A/B testing.

Capabilities:
  * ANALYTICS_TRACK_EVENT — track a custom event
  * ANALYTICS_IDENTIFY    — set user profile properties
  * ANALYTICS_QUERY       — export/query event data

Auth: Project token in request body (track), service account
      for data export.
Free tier: 20M events/month.
Pricing: usage-based after free tier.

Reference: https://developer.mixpanel.com/reference
"""
from __future__ import annotations

import base64
import json
from typing import Any

from ..base import AdapterResult, Capability
from ..errors import AdapterValidationError
from ._base import AnalyticsBaseAdapter


class MixpanelAdapter(AnalyticsBaseAdapter):
    name = "mixpanel"
    base_url = "https://api.mixpanel.com"
    config_alias = "mixpanel"

    priority = 80
    cost_per_call = 0.0

    # ── Track event ───────────────────────────────────────────

    def _do_track(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        event = params.get("event")
        if not event:
            raise AdapterValidationError(
                self.name, "'event' name is required",
            )
        distinct_id = params.get("distinct_id") or params.get("user_id")

        url = f"{self.base_url}/track"
        properties: dict[str, Any] = {
            "token": self._api_key(),
            **(params.get("properties", {})),
        }
        if distinct_id:
            properties["distinct_id"] = distinct_id

        body = [{"event": event, "properties": properties}]

        raw = self._http_post(url, body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "event": event,
                "distinct_id": distinct_id or "",
                "tracked": True,
            },
            raw=raw,
        )

    # ── Identify (people/set) ─────────────────────────────────

    def _do_identify(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        distinct_id = params.get("distinct_id") or params.get("user_id")
        if not distinct_id:
            raise AdapterValidationError(
                self.name, "'distinct_id' is required",
            )

        url = f"{self.base_url}/engage#profile-set"
        body = [{
            "$token": self._api_key(),
            "$distinct_id": distinct_id,
            "$set": params.get("properties", {}),
        }]

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

    # ── Query (export) ─────────────────────────────���──────────

    def _do_query(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        event = params.get("event")
        if not event:
            raise AdapterValidationError(
                self.name, "'event' name is required for query",
            )

        from_date = params.get("from_date", "2026-04-01")
        to_date = params.get("to_date", "2026-04-13")

        url = f"{self.base_url}/export"
        body = {
            "from_date": from_date,
            "to_date": to_date,
            "event": [event],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        raw = self._http_post(url, body, headers=headers)

        results = raw if isinstance(raw, list) else raw.get("results", []) if isinstance(raw, dict) else []

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "event": event,
                "results": results,
                "count": len(results),
                "from_date": from_date,
                "to_date": to_date,
            },
            raw=raw,
        )
