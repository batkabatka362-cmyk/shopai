"""Ads API — fetches ad performance data from platforms."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("data.ads_api")


class AdsAPI:
    """Fetches ad data from advertising platforms (Meta, Google, TikTok)."""

    def __init__(self, platform: str = "meta", api_key: str = "") -> None:
        self._platform = platform
        self._api_key = api_key

    def fetch_campaigns(self) -> list[dict[str, Any]]:
        logger.info("[%s] Fetching campaigns", self._platform)
        return []

    def fetch_ad_performance(self, campaign_id: str) -> dict[str, Any]:
        logger.info("[%s] Fetching ad performance: %s", self._platform, campaign_id)
        return {}

    def fetch_audience_insights(self) -> dict[str, Any]:
        logger.info("[%s] Fetching audience insights", self._platform)
        return {}
