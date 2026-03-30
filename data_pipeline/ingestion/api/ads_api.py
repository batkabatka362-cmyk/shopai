"""AdsAPI — fetches ad-performance data from Facebook, Google, and TikTok.

All three platform methods return a normalised campaign structure:
    {
        "platform":    str,
        "campaign_id": str,
        "impressions": int,
        "clicks":      int,
        "spend":       float,
        "conversions": int,
    }
"""
from __future__ import annotations

import logging
import time
from typing import Any

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = logging.getLogger("data_pipeline.ads_api")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NORMALIZED_KEYS = ("platform", "campaign_id", "impressions", "clicks", "spend", "conversions")


def _empty_record(platform: str, campaign_id: str = "") -> dict[str, Any]:
    return {
        "platform": platform,
        "campaign_id": campaign_id,
        "impressions": 0,
        "clicks": 0,
        "spend": 0.0,
        "conversions": 0,
    }


def _safe_get(
    url: str,
    params: dict[str, Any],
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> dict[str, Any]:
    """Perform a GET request with retry; returns parsed JSON or an empty dict."""
    if not _REQUESTS_AVAILABLE:
        logger.warning("requests not installed; skipping HTTP call to %s", url)
        return {}

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = _requests.get(url, params=params, headers=headers or {}, timeout=30)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", retry_delay * attempt))
                logger.warning("Rate-limited (%s); sleeping %.1fs", url, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < max_retries:
                time.sleep(retry_delay * attempt)

    logger.error("HTTP GET failed after %d attempts for %s: %s", max_retries, url, last_exc)
    return {}


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class AdsAPI:
    """Unified adapter for Facebook, Google, and TikTok Ads APIs."""

    # ------------------------------------------------------------------
    # Facebook / Meta Ads
    # ------------------------------------------------------------------

    _FB_BASE = "https://graph.facebook.com/v19.0"

    def fetch_facebook_ads(
        self,
        account_id: str,
        access_token: str,
        date_range: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch campaign-level insights from the Meta Marketing API.

        Args:
            account_id:   Meta ad-account ID, e.g. ``act_123456789``.
            access_token: Meta user or system-user access token.
            date_range:   ``{"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"}``.
                          Defaults to the last 30 days if omitted.

        Returns:
            ``{"platform": "facebook", "campaigns": [...], "errors": [...]}``
        """
        date_range = date_range or self._default_date_range(30)
        url = f"{self._FB_BASE}/{account_id}/insights"
        params: dict[str, Any] = {
            "access_token": access_token,
            "level": "campaign",
            "fields": "campaign_id,campaign_name,impressions,clicks,spend,actions",
            "time_range": (
                f'{{"since":"{date_range["since"]}","until":"{date_range["until"]}"}}'
            ),
            "limit": 500,
        }

        raw = _safe_get(url, params)
        campaigns: list[dict[str, Any]] = []
        errors: list[str] = []

        for item in raw.get("data", []):
            try:
                record = _empty_record("facebook", item.get("campaign_id", ""))
                record["impressions"] = int(item.get("impressions", 0))
                record["clicks"] = int(item.get("clicks", 0))
                record["spend"] = float(item.get("spend", 0.0))
                record["conversions"] = self._fb_extract_conversions(item.get("actions", []))
                record["campaign_name"] = item.get("campaign_name", "")
                campaigns.append(record)
            except (ValueError, TypeError) as exc:
                errors.append(f"Parse error for campaign {item.get('campaign_id')}: {exc}")

        logger.info("Facebook Ads: fetched %d campaigns", len(campaigns))
        return {"platform": "facebook", "campaigns": campaigns, "errors": errors}

    @staticmethod
    def _fb_extract_conversions(actions: list[dict[str, Any]]) -> int:
        """Sum all purchase/conversion action counts from the Meta actions array."""
        total = 0
        conversion_types = {
            "purchase",
            "offsite_conversion.fb_pixel_purchase",
            "omni_purchase",
        }
        for action in actions:
            if action.get("action_type") in conversion_types:
                try:
                    total += int(float(action.get("value", 0)))
                except (ValueError, TypeError):
                    pass
        return total

    # ------------------------------------------------------------------
    # Google Ads
    # ------------------------------------------------------------------

    _GOOGLE_ADS_BASE = "https://googleads.googleapis.com/v16"

    def fetch_google_ads(
        self,
        customer_id: str,
        credentials: dict[str, str],
        date_range: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch campaign-level performance from Google Ads API (GAQL).

        Args:
            customer_id:  Google Ads customer ID (digits only, no dashes).
            credentials:  ``{"developer_token": str, "access_token": str}``.
            date_range:   ``{"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"}``.

        Returns:
            ``{"platform": "google", "campaigns": [...], "errors": [...]}``
        """
        date_range = date_range or self._default_date_range(30)
        url = f"{self._GOOGLE_ADS_BASE}/customers/{customer_id}/googleAds:search"
        headers = {
            "Authorization": f"Bearer {credentials.get('access_token', '')}",
            "developer-token": credentials.get("developer_token", ""),
            "Content-Type": "application/json",
        }
        gaql = (
            "SELECT campaign.id, campaign.name, "
            "metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions "
            "FROM campaign "
            f"WHERE segments.date BETWEEN '{date_range['since']}' AND '{date_range['until']}' "
            "ORDER BY metrics.impressions DESC"
        )

        campaigns: list[dict[str, Any]] = []
        errors: list[str] = []

        if not _REQUESTS_AVAILABLE:
            logger.warning("requests not installed; returning empty Google Ads response")
            return {"platform": "google", "campaigns": campaigns, "errors": errors}

        try:
            resp = _requests.post(url, headers=headers, json={"query": gaql}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("Google Ads request failed: %s", exc)
            return {"platform": "google", "campaigns": campaigns, "errors": [str(exc)]}

        for row in data.get("results", []):
            try:
                campaign = row.get("campaign", {})
                metrics = row.get("metrics", {})
                record = _empty_record("google", str(campaign.get("id", "")))
                record["impressions"] = int(metrics.get("impressions", 0))
                record["clicks"] = int(metrics.get("clicks", 0))
                # Google reports cost in micros (millionths of the account currency)
                record["spend"] = round(int(metrics.get("costMicros", 0)) / 1_000_000, 2)
                record["conversions"] = int(float(metrics.get("conversions", 0)))
                record["campaign_name"] = campaign.get("name", "")
                campaigns.append(record)
            except (ValueError, TypeError, KeyError) as exc:
                errors.append(f"Parse error: {exc}")

        logger.info("Google Ads: fetched %d campaigns", len(campaigns))
        return {"platform": "google", "campaigns": campaigns, "errors": errors}

    # ------------------------------------------------------------------
    # TikTok Ads
    # ------------------------------------------------------------------

    _TIKTOK_BASE = "https://business-api.tiktok.com/open_api/v1.3"

    def fetch_tiktok_ads(
        self,
        advertiser_id: str,
        access_token: str,
        date_range: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch campaign-level report from TikTok Business API.

        Args:
            advertiser_id: TikTok advertiser ID.
            access_token:  Long-lived access token.
            date_range:    ``{"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"}``.

        Returns:
            ``{"platform": "tiktok", "campaigns": [...], "errors": [...]}``
        """
        date_range = date_range or self._default_date_range(30)
        url = f"{self._TIKTOK_BASE}/report/integrated/get/"
        params: dict[str, Any] = {
            "advertiser_id": advertiser_id,
            "report_type": "BASIC",
            "dimensions": '["campaign_id"]',
            "metrics": '["campaign_name","impressions","clicks","spend","conversions"]',
            "start_date": date_range["since"],
            "end_date": date_range["until"],
            "page_size": 1000,
        }
        headers = {"Access-Token": access_token}

        raw = _safe_get(url, params, headers)
        campaigns: list[dict[str, Any]] = []
        errors: list[str] = []

        rows = raw.get("data", {}).get("list", [])
        for item in rows:
            try:
                dims = item.get("dimensions", {})
                metrics = item.get("metrics", {})
                record = _empty_record("tiktok", dims.get("campaign_id", ""))
                record["impressions"] = int(metrics.get("impressions", 0))
                record["clicks"] = int(metrics.get("clicks", 0))
                record["spend"] = float(metrics.get("spend", 0.0))
                record["conversions"] = int(metrics.get("conversions", 0))
                record["campaign_name"] = metrics.get("campaign_name", "")
                campaigns.append(record)
            except (ValueError, TypeError) as exc:
                errors.append(f"TikTok parse error: {exc}")

        logger.info("TikTok Ads: fetched %d campaigns", len(campaigns))
        return {"platform": "tiktok", "campaigns": campaigns, "errors": errors}

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _default_date_range(days: int) -> dict[str, str]:
        """Return ``{"since": ..., "until": ...}`` covering the last *days* days."""
        import datetime

        today = datetime.date.today()
        since = today - datetime.timedelta(days=days)
        return {"since": since.isoformat(), "until": today.isoformat()}
