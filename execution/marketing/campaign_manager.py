"""CampaignManager — manages marketing campaigns across ad platforms.

Uses only the Python standard library (urllib.request).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Per-platform endpoint builders
# ---------------------------------------------------------------------------

def _fb_campaign_url(campaign_id: str, version: str = "v19.0") -> str:
    return f"https://graph.facebook.com/{version}/{campaign_id}"


def _google_campaign_url(customer_id: str, campaign_id: str, version: str = "v14") -> str:
    cid = customer_id.replace("-", "")
    return f"https://googleads.googleapis.com/{version}/customers/{cid}/campaigns/{campaign_id}"


def _tiktok_campaign_url(version: str = "v1.3") -> str:
    return f"https://business-api.tiktok.com/open_api/{version}/campaign/update/"


class CampaignManager:
    """Get status, pause, resume, update budget, and fetch metrics for
    campaigns on Facebook, Google, and TikTok Ads."""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_campaign_status(
        self,
        platform: str,
        campaign_id: str,
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch current status of a campaign.

        Args:
            platform:    ``"facebook"``, ``"google"``, or ``"tiktok"``.
            campaign_id: Platform campaign ID.
            credentials: Platform-specific auth dict (see per-method docs).

        Returns:
            ``{"platform": str, "campaign_id": str, "status": str,
               "raw": {...}}``
        """
        try:
            raw = self._get_raw_campaign(platform, campaign_id, credentials)
            status = self._extract_status(platform, raw)
            return {
                "platform": platform,
                "campaign_id": campaign_id,
                "status": status,
                "raw": raw,
            }
        except Exception as exc:
            return {"status": "error", "platform": platform,
                    "campaign_id": campaign_id, "error": str(exc)}

    def pause_campaign(
        self,
        platform: str,
        campaign_id: str,
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Set a campaign's delivery status to PAUSED."""
        return self._set_campaign_status(platform, campaign_id, credentials, "PAUSED")

    def resume_campaign(
        self,
        platform: str,
        campaign_id: str,
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Set a campaign's delivery status to ACTIVE/ENABLED."""
        active_status = {
            "facebook": "ACTIVE",
            "google": "ENABLED",
            "tiktok": "ENABLE",
        }.get(platform, "ACTIVE")
        return self._set_campaign_status(platform, campaign_id, credentials, active_status)

    def update_campaign_budget(
        self,
        platform: str,
        campaign_id: str,
        new_budget: float,
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Update the daily/lifetime budget of a campaign.

        Args:
            new_budget: Budget in the account's currency (e.g. USD).

        Returns:
            ``{"platform": str, "campaign_id": str, "status": str,
               "new_budget": float, "raw": {...}}``
        """
        try:
            raw = self._update_budget_on_platform(
                platform, campaign_id, new_budget, credentials
            )
            return {
                "platform": platform,
                "campaign_id": campaign_id,
                "status": "updated",
                "new_budget": new_budget,
                "raw": raw,
            }
        except Exception as exc:
            return {
                "status": "error",
                "platform": platform,
                "campaign_id": campaign_id,
                "error": str(exc),
            }

    def get_campaign_metrics(
        self,
        platform: str,
        campaign_id: str,
        date_range: dict[str, str],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Retrieve campaign performance metrics.

        Args:
            date_range: ``{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}``

        Returns:
            ``{"platform": str, "campaign_id": str, "impressions": int,
               "clicks": int, "spend": float, "conversions": int,
               "roas": float, "date_range": {...}}``
        """
        try:
            raw = self._fetch_metrics(platform, campaign_id, date_range, credentials)
            metrics = self._parse_metrics(platform, raw)
            return {
                "platform": platform,
                "campaign_id": campaign_id,
                "date_range": date_range,
                **metrics,
                "raw": raw,
            }
        except Exception as exc:
            return {
                "status": "error",
                "platform": platform,
                "campaign_id": campaign_id,
                "error": str(exc),
            }

    # ------------------------------------------------------------------ #
    # Private — platform dispatch helpers                                  #
    # ------------------------------------------------------------------ #

    def _get_raw_campaign(
        self,
        platform: str,
        campaign_id: str,
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        if platform == "facebook":
            access_token = credentials.get("access_token", "")
            url = (
                f"{_fb_campaign_url(campaign_id)}"
                f"?fields=id,name,status,effective_status&access_token={access_token}"
            )
            return self._make_request("GET", url, {})

        if platform == "google":
            customer_id = credentials.get("customer_id", "")
            url = (
                f"https://googleads.googleapis.com/v14/customers/"
                f"{customer_id.replace('-', '')}/googleAds:searchStream"
            )
            headers = {
                "Authorization": f"Bearer {credentials.get('access_token', '')}",
                "developer-token": credentials.get("developer_token", ""),
            }
            payload = {
                "query": (
                    f"SELECT campaign.id, campaign.name, campaign.status "
                    f"FROM campaign WHERE campaign.id = {campaign_id}"
                )
            }
            return self._make_request("POST", url, headers, payload)

        if platform == "tiktok":
            access_token = credentials.get("access_token", "")
            advertiser_id = credentials.get("advertiser_id", "")
            url = (
                f"https://business-api.tiktok.com/open_api/v1.3/campaign/get/"
                f"?advertiser_id={advertiser_id}&campaign_ids=[{campaign_id}]"
            )
            headers = {"Access-Token": access_token}
            return self._make_request("GET", url, headers)

        raise ValueError(f"Unsupported platform: {platform!r}")

    def _set_campaign_status(
        self,
        platform: str,
        campaign_id: str,
        credentials: dict[str, Any],
        new_status: str,
    ) -> dict[str, Any]:
        try:
            if platform == "facebook":
                access_token = credentials.get("access_token", "")
                url = _fb_campaign_url(campaign_id)
                # Facebook Graph API uses form-encoded PATCH
                import urllib.parse
                data = urllib.parse.urlencode(
                    {"status": new_status, "access_token": access_token}
                ).encode()
                raw = self._make_request("POST", url, {}, _raw_data=data)
            elif platform == "google":
                customer_id = credentials.get("customer_id", "").replace("-", "")
                url = (
                    f"https://googleads.googleapis.com/v14/customers/{customer_id}"
                    f"/campaigns:mutate"
                )
                headers = {
                    "Authorization": f"Bearer {credentials.get('access_token', '')}",
                    "developer-token": credentials.get("developer_token", ""),
                }
                payload = {
                    "operations": [
                        {
                            "update": {
                                "resourceName": (
                                    f"customers/{customer_id}/campaigns/{campaign_id}"
                                ),
                                "status": new_status,
                            },
                            "updateMask": "status",
                        }
                    ]
                }
                raw = self._make_request("POST", url, headers, payload)
            elif platform == "tiktok":
                access_token = credentials.get("access_token", "")
                advertiser_id = credentials.get("advertiser_id", "")
                url = _tiktok_campaign_url()
                headers = {
                    "Access-Token": access_token,
                    "Content-Type": "application/json",
                }
                payload = {
                    "advertiser_id": advertiser_id,
                    "campaign_id": campaign_id,
                    "operation_status": new_status,
                }
                raw = self._make_request("POST", url, headers, payload)
            else:
                raise ValueError(f"Unsupported platform: {platform!r}")

            return {
                "platform": platform,
                "campaign_id": campaign_id,
                "status": new_status.lower(),
                "raw": raw,
            }
        except Exception as exc:
            return {
                "status": "error",
                "platform": platform,
                "campaign_id": campaign_id,
                "error": str(exc),
            }

    def _update_budget_on_platform(
        self,
        platform: str,
        campaign_id: str,
        new_budget: float,
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        if platform == "facebook":
            import urllib.parse
            access_token = credentials.get("access_token", "")
            url = _fb_campaign_url(campaign_id)
            data = urllib.parse.urlencode(
                {
                    "daily_budget": int(new_budget * 100),
                    "access_token": access_token,
                }
            ).encode()
            return self._make_request("POST", url, {}, _raw_data=data)

        if platform == "google":
            customer_id = credentials.get("customer_id", "").replace("-", "")
            url = (
                f"https://googleads.googleapis.com/v14/customers/{customer_id}"
                f"/campaigns:mutate"
            )
            headers = {
                "Authorization": f"Bearer {credentials.get('access_token', '')}",
                "developer-token": credentials.get("developer_token", ""),
            }
            budget_micros = int(new_budget * 1_000_000)
            payload = {
                "operations": [
                    {
                        "update": {
                            "resourceName": (
                                f"customers/{customer_id}/campaigns/{campaign_id}"
                            ),
                            "campaignBudget": {
                                "amountMicros": str(budget_micros)
                            },
                        },
                        "updateMask": "campaign_budget.amount_micros",
                    }
                ]
            }
            return self._make_request("POST", url, headers, payload)

        if platform == "tiktok":
            access_token = credentials.get("access_token", "")
            advertiser_id = credentials.get("advertiser_id", "")
            url = _tiktok_campaign_url()
            headers = {
                "Access-Token": access_token,
                "Content-Type": "application/json",
            }
            payload = {
                "advertiser_id": advertiser_id,
                "campaign_id": campaign_id,
                "budget": new_budget,
                "budget_mode": credentials.get("budget_mode", "BUDGET_MODE_DAY"),
            }
            return self._make_request("POST", url, headers, payload)

        raise ValueError(f"Unsupported platform: {platform!r}")

    def _fetch_metrics(
        self,
        platform: str,
        campaign_id: str,
        date_range: dict[str, str],
        credentials: dict[str, Any],
    ) -> dict[str, Any]:
        start = date_range.get("start", "")
        end = date_range.get("end", "")

        if platform == "facebook":
            access_token = credentials.get("access_token", "")
            fields = "impressions,clicks,spend,actions,action_values"
            url = (
                f"{_fb_campaign_url(campaign_id)}/insights"
                f"?fields={fields}"
                f"&time_range={{\"since\":\"{start}\",\"until\":\"{end}\"}}"
                f"&access_token={access_token}"
            )
            return self._make_request("GET", url, {})

        if platform == "google":
            customer_id = credentials.get("customer_id", "").replace("-", "")
            url = (
                f"https://googleads.googleapis.com/v14/customers/"
                f"{customer_id}/googleAds:searchStream"
            )
            headers = {
                "Authorization": f"Bearer {credentials.get('access_token', '')}",
                "developer-token": credentials.get("developer_token", ""),
            }
            payload = {
                "query": (
                    "SELECT campaign.id, metrics.impressions, metrics.clicks, "
                    "metrics.cost_micros, metrics.conversions, metrics.conversions_value "
                    f"FROM campaign WHERE campaign.id = {campaign_id} "
                    f"AND segments.date BETWEEN '{start}' AND '{end}'"
                )
            }
            return self._make_request("POST", url, headers, payload)

        if platform == "tiktok":
            access_token = credentials.get("access_token", "")
            advertiser_id = credentials.get("advertiser_id", "")
            url = (
                f"https://business-api.tiktok.com/open_api/v1.3/report/integrated/get/"
                f"?advertiser_id={advertiser_id}"
                f"&report_type=BASIC"
                f"&dimensions=[\"campaign_id\"]"
                f"&metrics=[\"impressions\",\"clicks\",\"spend\",\"conversions\"]"
                f"&start_date={start}&end_date={end}"
                f"&filtering=[{{\"field_name\":\"campaign_id\","
                f"\"filter_type\":\"IN\",\"filter_value\":[\"{campaign_id}\"]}}]"
            )
            headers = {"Access-Token": access_token}
            return self._make_request("GET", url, headers)

        raise ValueError(f"Unsupported platform: {platform!r}")

    def _parse_metrics(
        self, platform: str, raw: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract normalised metric values from a raw API response."""
        impressions = clicks = conversions = 0
        spend = revenue = 0.0

        if platform == "facebook":
            data = raw.get("data", [{}])
            row = data[0] if data else {}
            impressions = int(row.get("impressions", 0))
            clicks = int(row.get("clicks", 0))
            spend = float(row.get("spend", 0.0))
            for action in row.get("action_values", []):
                if action.get("action_type") == "purchase":
                    revenue += float(action.get("value", 0))
            for action in row.get("actions", []):
                if action.get("action_type") == "purchase":
                    conversions += int(action.get("value", 0))

        elif platform == "google":
            for result_group in raw:
                for row in result_group.get("results", []):
                    m = row.get("metrics", {})
                    impressions += int(m.get("impressions", 0))
                    clicks += int(m.get("clicks", 0))
                    spend += int(m.get("costMicros", 0)) / 1_000_000
                    conversions += float(m.get("conversions", 0))
                    revenue += float(m.get("conversionsValue", 0))

        elif platform == "tiktok":
            data = raw.get("data", {}).get("list", [])
            for row in data:
                m = row.get("metrics", {})
                impressions += int(m.get("impressions", 0))
                clicks += int(m.get("clicks", 0))
                spend += float(m.get("spend", 0))
                conversions += int(m.get("conversions", 0))

        roas = round(revenue / spend, 4) if spend > 0 else 0.0
        return {
            "impressions": impressions,
            "clicks": clicks,
            "spend": round(spend, 2),
            "conversions": int(conversions),
            "roas": roas,
        }

    def _extract_status(self, platform: str, raw: dict[str, Any]) -> str:
        if platform == "facebook":
            return str(
                raw.get("effective_status", raw.get("status", "unknown"))
            ).lower()
        if platform == "google":
            for result_group in (raw if isinstance(raw, list) else [raw]):
                for row in result_group.get("results", []):
                    return str(row.get("campaign", {}).get("status", "unknown")).lower()
        if platform == "tiktok":
            items = (
                raw.get("data", {}).get("list", [])
                if isinstance(raw.get("data"), dict)
                else []
            )
            if items:
                return str(items[0].get("operation_status", "unknown")).lower()
        return "unknown"

    # ------------------------------------------------------------------ #
    # HTTP                                                                 #
    # ------------------------------------------------------------------ #

    def _make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        *,
        _raw_data: bytes | None = None,
    ) -> dict[str, Any]:
        data: bytes | None = _raw_data
        if payload is not None and _raw_data is None:
            data = json.dumps(payload).encode("utf-8")
            headers = {**headers, "Content-Type": "application/json"}

        max_retries = 3
        delay = 1.0
        for attempt in range(max_retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < max_retries:
                    retry_after = float(exc.headers.get("Retry-After", delay))
                    time.sleep(retry_after)
                    delay *= 2
                    continue
                body = exc.read().decode("utf-8", errors="replace")
                raise urllib.error.HTTPError(
                    url, exc.code, f"{exc.reason} — {body}", exc.headers, None
                ) from exc
            except urllib.error.URLError:
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise
        raise RuntimeError(f"Request to {url} failed after {max_retries} retries.")
