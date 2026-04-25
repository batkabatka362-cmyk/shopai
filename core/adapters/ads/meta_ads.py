"""MetaAdsAdapter — Meta (Facebook/Instagram) Marketing API.

Meta Ads covers Facebook, Instagram, Messenger, and Audience
Network advertising. This adapter wraps the Marketing API
(defaults to v25.0 — the Q1 2026 GA that deprecated ASC/AAC
smart-promotion shims + the 7dv/28dv attribution windows).

Capabilities:

  * **Performance** — fetch campaign insights (reach, impressions,
    spend, conversions); deprecated attribution windows in
    ``action_attribution_windows`` are translated to the
    2026 codes so existing callers don't 400-fail.
  * **Campaigns** — create new campaigns.
  * **Budget** — update daily/lifetime budget.

Configurable overrides (2026 API rollover):

  * ``SHOPAI_META_API_VERSION`` env var — override the graph
    version used in the base URL (e.g. ``v26.0`` when it GAs).
  * ``SHOPAI_META_ATTRIBUTION_REMAP`` env var — set to ``0``
    to disable the 7dv/28dv → 1dv/7dv_click translation and
    pass the caller's windows through unmodified.

Free tier: None (pay-per-impression/click).
Reference: https://developers.facebook.com/docs/marketing-apis
"""
from __future__ import annotations

import os
from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterValidationError
from ._base import AdsBaseAdapter


_DEFAULT_META_API_VERSION = "v25.0"

# Q1 2026 deprecation map — old code → new code.
# Callers that still construct insights queries with the old
# 7dv/28dv windows would get a 400; we translate proactively.
_ATTRIBUTION_WINDOW_REMAP = {
    "7dv": "1dv",
    "28dv": "7dv_click",
}


def _resolved_api_version() -> str:
    """Resolve the Graph API version (env override or default).
    Read per-instance rather than captured at import time so a
    long-running daemon can rotate versions without reboot."""
    override = os.environ.get(
        "SHOPAI_META_API_VERSION", "",
    ).strip()
    return override or _DEFAULT_META_API_VERSION


def _normalize_attribution_windows(
    windows: Any,
) -> list[str]:
    """Translate deprecated 7dv/28dv attribution windows to
    their 2026 equivalents. Unknown codes pass through so new
    windows (1d_view, 7d_click, etc.) still work. Returns a
    de-duplicated list preserving input order.

    Opt-out via ``SHOPAI_META_ATTRIBUTION_REMAP=0``.
    """
    if os.environ.get(
        "SHOPAI_META_ATTRIBUTION_REMAP", "",
    ) == "0":
        if isinstance(windows, list):
            return [str(w) for w in windows]
        if windows is None:
            return []
        return [str(windows)]
    if windows is None:
        return []
    if not isinstance(windows, list):
        windows = [windows]
    out: list[str] = []
    seen: set[str] = set()
    for w in windows:
        code = str(w)
        mapped = _ATTRIBUTION_WINDOW_REMAP.get(code, code)
        if mapped in seen:
            continue
        seen.add(mapped)
        out.append(mapped)
    return out


class MetaAdsAdapter(AdsBaseAdapter):
    name = "meta_ads"
    config_alias = "meta_ads_access_token"
    priority = 80
    cost_per_call = 0.0

    @property
    def base_url(self) -> str:  # type: ignore[override]
        """Graph API base URL, re-evaluated per call so
        ``SHOPAI_META_API_VERSION`` env overrides land without
        an adapter reload."""
        return (
            f"https://graph.facebook.com/"
            f"{_resolved_api_version()}"
        )

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
        # Optional attribution window override — Q1 2026
        # Meta rollover deprecated 7dv/28dv; translate proactively
        # so callers that still pass the old codes keep working.
        windows = _normalize_attribution_windows(
            params.get("action_attribution_windows"),
        )
        if windows:
            import urllib.parse as _qs
            url += (
                "&action_attribution_windows="
                + _qs.quote(",".join(windows))
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
