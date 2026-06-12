"""GA4Adapter -- Google Analytics 4 Measurement Protocol.

API docs:
  https://developers.google.com/analytics/devguides/collection/protocol/ga4

Endpoint:
  POST https://www.google-analytics.com/mp/collect
       ?measurement_id=<MID>&api_secret=<SECRET>

Body:
  {
    "client_id": "<cid>",
    "events": [
      {"name": "purchase", "params": {...}},
    ],
  }

Returns 204 No Content on success (no body).

Per-store routing via W963-117:
  SHOPAI_STORE_<SID>_GA4_MEASUREMENT_ID
  SHOPAI_STORE_<SID>_GA4_API_SECRET
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..config import get_config
from .._per_store_credentials import (
    resolve_per_store as _resolve_per_store,
)
from ..errors import AdapterNotConfigured
from ._base import AnalyticsBaseAdapter


class GA4Adapter(AnalyticsBaseAdapter):
    """Google Analytics 4 Measurement Protocol sink."""

    name = "ga4"
    base_url = "https://www.google-analytics.com"
    # The actual "key" is api_secret; measurement_id is a
    # separate identifier. is_configured needs both.
    config_alias = "ga4_api_secret"
    cost_per_call = 0.0

    # ── Configuration ──────────────────────────────────────────

    def _measurement_id(self) -> str:
        mid = (
            _resolve_per_store("ga4_measurement_id")
            or get_config().get("ga4_measurement_id")
            or ""
        )
        if not mid:
            raise AdapterNotConfigured(
                self.name,
                "missing GA4_MEASUREMENT_ID (per-store "
                "or fleet)",
            )
        return mid

    def is_configured(self) -> bool:
        # Need both api_secret AND measurement_id
        if not (
            _resolve_per_store(self.config_alias)
            or get_config().get(self.config_alias)
        ):
            return False
        if not (
            _resolve_per_store("ga4_measurement_id")
            or get_config().get("ga4_measurement_id")
        ):
            return False
        return True

    # ── Auth via query params (Measurement Protocol) ──────────

    def _auth_query(self) -> str:
        return urlencode({
            "measurement_id": self._measurement_id(),
            "api_secret": self._api_key(),
        })

    # ── Paths ─────────────────────────────────────────────────

    def _track_event_path(self) -> str:
        return f"/mp/collect?{self._auth_query()}"

    def _identify_path(self) -> str:
        # Measurement Protocol doesn't have a distinct
        # 'identify' endpoint. We send a 'user_engagement'
        # event with user_id which serves the same
        # mapping purpose.
        return f"/mp/collect?{self._auth_query()}"

    # ── Payload shapes ────────────────────────────────────────

    def _build_event_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        event_name = kwargs["event_name"]
        user_id = str(kwargs["user_id"])
        ep = kwargs.get("event_params") or {}
        if not isinstance(ep, dict):
            ep = {}
        # Required by GA4: engagement_time_msec for
        # session tracking. Add a sane default if not
        # supplied.
        if "engagement_time_msec" not in ep:
            ep["engagement_time_msec"] = 100
        event: dict[str, Any] = {
            "name": event_name,
            "params": ep,
        }
        ts = kwargs.get("timestamp_micros") or 0
        try:
            ts_int = int(ts)
        except (TypeError, ValueError):
            ts_int = 0
        body: dict[str, Any] = {
            "client_id": user_id,
            "events": [event],
        }
        # GA4 distinguishes client_id (device-scoped)
        # from user_id (account-scoped). When the
        # caller passed a "user_id" key we ALSO set
        # the top-level user_id to enable cross-device
        # attribution.
        original = kwargs.get(
            "user_id",
        )
        if original and isinstance(original, str):
            body["user_id"] = original
        if ts_int > 0:
            body["timestamp_micros"] = ts_int
        return body

    def _build_identify_payload(
        self, **kwargs: Any,
    ) -> dict[str, Any]:
        user_id = str(kwargs["user_id"])
        traits = kwargs.get("traits") or {}
        if not isinstance(traits, dict):
            traits = {}
        traits["engagement_time_msec"] = (
            traits.get("engagement_time_msec", 100)
        )
        return {
            "client_id": user_id,
            "user_id": user_id,
            "events": [{
                "name": "user_engagement",
                "params": traits,
            }],
        }
