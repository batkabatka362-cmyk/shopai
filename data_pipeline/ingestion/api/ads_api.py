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

from utils.helpers import safe_float, safe_int
# Reuse the Retry-After parser from the Shopify client (pass
# 43) — handles both delta-seconds and RFC 7231 HTTP-date
# forms. Pre-audit all three ad platforms did
# ``float(resp.headers.get("Retry-After"))`` which crashed on
# the date form. Audit pass 46.
from .shopify_api import _parse_retry_after

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
    """Perform a GET request with retry; returns parsed JSON or a dict
    containing ``"_error"`` on failure."""
    if not _REQUESTS_AVAILABLE:
        logger.warning("requests not installed; skipping HTTP call to %s", url)
        return {"_error": "requests library not installed"}

    last_exc: Exception | None = None
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            resp = _requests.get(url, params=params, headers=headers or {}, timeout=30)
            if resp.status_code == 429:
                wait = _parse_retry_after(
                    resp.headers.get("Retry-After", ""),
                    retry_delay * attempt,
                )
                logger.warning("Rate-limited (%s); sleeping %.1fs", url, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError as exc:
                return {"_error": f"invalid JSON: {exc}"}
            return payload if isinstance(payload, dict) else {"_error": "non-dict response"}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < max_retries:
                time.sleep(retry_delay * attempt)

    logger.error("HTTP GET failed after %d attempts for %s: %s", max_retries, url, last_exc)
    return {"_error": f"failed after {max_retries} attempts: {last_exc}"}


def _safe_post(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> dict[str, Any]:
    """POST with retry (used by the Google Ads path). Audit pass 46:
    pre-audit Google Ads had NO retry at all — a single 429 or 5xx
    lost the entire request."""
    if not _REQUESTS_AVAILABLE:
        logger.warning("requests not installed; skipping HTTP call to %s", url)
        return {"_error": "requests library not installed"}

    last_exc: Exception | None = None
    for attempt in range(1, max(1, max_retries) + 1):
        try:
            resp = _requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 429:
                wait = _parse_retry_after(
                    resp.headers.get("Retry-After", ""),
                    retry_delay * attempt,
                )
                logger.warning("Rate-limited (%s); sleeping %.1fs", url, wait)
                time.sleep(wait)
                continue
            if 500 <= resp.status_code < 600:
                last_exc = Exception(f"HTTP {resp.status_code}")
                if attempt < max_retries:
                    time.sleep(retry_delay * attempt)
                    continue
                return {"_error": f"HTTP {resp.status_code}"}
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError as exc:
                return {"_error": f"invalid JSON: {exc}"}
            return data if isinstance(data, dict) else {"_error": "non-dict response"}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < max_retries:
                time.sleep(retry_delay * attempt)

    logger.error("HTTP POST failed after %d attempts for %s: %s", max_retries, url, last_exc)
    return {"_error": f"failed after {max_retries} attempts: {last_exc}"}


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
        # Defensive coercion of public entry point. Audit pass 46.
        account_id = account_id if isinstance(account_id, str) else ""
        access_token = access_token if isinstance(access_token, str) else ""
        date_range = self._ensure_date_range(date_range, 30)

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

        if "_error" in raw:
            errors.append(raw["_error"])
            return {"platform": "facebook", "campaigns": campaigns, "errors": errors}

        data = raw.get("data") or []
        if not isinstance(data, list):
            data = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                record = _empty_record("facebook", str(item.get("campaign_id") or ""))
                record["impressions"] = safe_int(item.get("impressions"))
                record["clicks"] = safe_int(item.get("clicks"))
                record["spend"] = safe_float(item.get("spend"))
                record["conversions"] = self._fb_extract_conversions(item.get("actions"))
                record["campaign_name"] = item.get("campaign_name") or ""
                campaigns.append(record)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Parse error for campaign {item.get('campaign_id')}: {exc}")

        logger.info("Facebook Ads: fetched %d campaigns", len(campaigns))
        return {"platform": "facebook", "campaigns": campaigns, "errors": errors}

    @staticmethod
    def _fb_extract_conversions(actions: Any) -> int:
        """Sum all purchase/conversion action counts from the Meta actions array.

        Pre-audit assumed ``actions`` was always a list; a
        present-but-None ``"actions": null`` from the API
        crashed ``for action in None``. Audit pass 46.
        """
        if not isinstance(actions, list):
            return 0
        total = 0
        conversion_types = {
            "purchase",
            "offsite_conversion.fb_pixel_purchase",
            "omni_purchase",
        }
        for action in actions:
            if not isinstance(action, dict):
                continue
            if action.get("action_type") in conversion_types:
                total += safe_int(safe_float(action.get("value")))
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
        customer_id = customer_id if isinstance(customer_id, str) else ""
        credentials = credentials if isinstance(credentials, dict) else {}
        date_range = self._ensure_date_range(date_range, 30)

        url = f"{self._GOOGLE_ADS_BASE}/customers/{customer_id}/googleAds:search"
        headers = {
            "Authorization": f"Bearer {credentials.get('access_token') or ''}",
            "developer-token": credentials.get("developer_token") or "",
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

        # Pre-audit this path had NO retry on 429 / 5xx. Audit
        # pass 46 uses the shared ``_safe_post`` helper so
        # Google Ads has parity with the Facebook / TikTok
        # retry behaviour.
        data = _safe_post(url, headers, {"query": gaql})
        if "_error" in data:
            errors.append(data["_error"])
            return {"platform": "google", "campaigns": campaigns, "errors": errors}

        results = data.get("results") or []
        if not isinstance(results, list):
            results = []
        for row in results:
            if not isinstance(row, dict):
                continue
            try:
                campaign = row.get("campaign") or {}
                metrics = row.get("metrics") or {}
                if not isinstance(campaign, dict):
                    campaign = {}
                if not isinstance(metrics, dict):
                    metrics = {}
                record = _empty_record("google", str(campaign.get("id") or ""))
                record["impressions"] = safe_int(metrics.get("impressions"))
                record["clicks"] = safe_int(metrics.get("clicks"))
                # Google reports cost in micros (millionths of the account currency)
                record["spend"] = round(safe_int(metrics.get("costMicros")) / 1_000_000, 2)
                record["conversions"] = safe_int(safe_float(metrics.get("conversions")))
                record["campaign_name"] = campaign.get("name") or ""
                campaigns.append(record)
            except Exception as exc:  # noqa: BLE001
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
        advertiser_id = advertiser_id if isinstance(advertiser_id, str) else ""
        access_token = access_token if isinstance(access_token, str) else ""
        date_range = self._ensure_date_range(date_range, 30)

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

        if "_error" in raw:
            errors.append(raw["_error"])
            return {"platform": "tiktok", "campaigns": campaigns, "errors": errors}

        data = raw.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        rows = data.get("list") or []
        if not isinstance(rows, list):
            rows = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            try:
                dims = item.get("dimensions") or {}
                metrics = item.get("metrics") or {}
                if not isinstance(dims, dict):
                    dims = {}
                if not isinstance(metrics, dict):
                    metrics = {}
                record = _empty_record("tiktok", str(dims.get("campaign_id") or ""))
                record["impressions"] = safe_int(metrics.get("impressions"))
                record["clicks"] = safe_int(metrics.get("clicks"))
                record["spend"] = safe_float(metrics.get("spend"))
                record["conversions"] = safe_int(metrics.get("conversions"))
                record["campaign_name"] = metrics.get("campaign_name") or ""
                campaigns.append(record)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"TikTok parse error: {exc}")

        logger.info("TikTok Ads: fetched %d campaigns", len(campaigns))
        return {"platform": "tiktok", "campaigns": campaigns, "errors": errors}

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_date_range(
        cls,
        date_range: Any,
        default_days: int,
    ) -> dict[str, str]:
        """Coerce a caller-supplied date_range to a well-formed dict.

        Pre-audit the fetch methods did ``date_range or
        self._default_date_range(30)`` then unconditionally
        read ``date_range["since"]`` — a non-dict / missing-key
        input crashed. Audit pass 46.
        """
        if not isinstance(date_range, dict):
            return cls._default_date_range(default_days)
        since = date_range.get("since")
        until = date_range.get("until")
        if not isinstance(since, str) or not isinstance(until, str):
            return cls._default_date_range(default_days)
        return {"since": since, "until": until}

    @staticmethod
    def _default_date_range(days: int) -> dict[str, str]:
        """Return ``{"since": ..., "until": ...}`` covering the last *days* days."""
        import datetime

        if not isinstance(days, int) or days <= 0:
            days = 30
        today = datetime.date.today()
        since = today - datetime.timedelta(days=days)
        return {"since": since.isoformat(), "until": today.isoformat()}
