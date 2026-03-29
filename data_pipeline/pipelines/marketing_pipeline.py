"""MarketingPipeline — ingests, cleans, and feature-engineers ad campaign data."""
from __future__ import annotations

import logging
import time
from typing import Any

from data_pipeline.processing.cleaner import DataCleaner
from data_pipeline.processing.normalizer import DataNormalizer
from data_pipeline.processing.validator import DataValidator
from data_pipeline.feature_engineering.feature_builder import FeatureBuilder
from data_pipeline.feature_engineering.feature_store import FeatureStore
from data_pipeline.ingestion.api.ads_api import AdsAPI

logger = logging.getLogger("data_pipeline.marketing_pipeline")

# Validation schema for ad records
_ADS_SCHEMA: dict[str, Any] = {
    "required": ["campaign_id", "platform"],
    "types": {
        "impressions": "int",
        "clicks": "int",
        "spend": "float",
        "conversions": "int",
    },
    "ranges": {
        "impressions": {"min": 0},
        "clicks": {"min": 0},
        "spend": {"min": 0.0},
        "conversions": {"min": 0},
    },
}

_ADS_NORM_CONFIG: dict[str, Any] = {
    "date_fields": ["date", "created_at"],
}


def _compute_ad_metrics(record: dict[str, Any]) -> dict[str, Any]:
    """Compute derived performance metrics for a single campaign record.

    Adds the following keys (in-place on a copy):
    * ``ctr``              — click-through rate (clicks / impressions).
    * ``cpc``              — cost per click (spend / clicks).
    * ``roas``             — return on ad spend (revenue / spend).
    * ``conversion_rate``  — conversions / clicks.
    * ``cost_per_conversion`` — spend / conversions.
    """
    rec = dict(record)
    impressions = float(rec.get("impressions") or 0)
    clicks = float(rec.get("clicks") or 0)
    spend = float(rec.get("spend") or 0.0)
    conversions = float(rec.get("conversions") or 0)
    revenue = float(rec.get("revenue") or 0.0)

    rec["ctr"] = round(clicks / impressions, 6) if impressions > 0 else 0.0
    rec["cpc"] = round(spend / clicks, 4) if clicks > 0 else 0.0
    rec["roas"] = round(revenue / spend, 4) if spend > 0 else 0.0
    rec["conversion_rate"] = round(conversions / clicks, 6) if clicks > 0 else 0.0
    rec["cost_per_conversion"] = round(spend / conversions, 4) if conversions > 0 else 0.0
    return rec


class MarketingPipeline:
    """Raw → Clean → Validate → Normalize → Feature engineer for marketing data.

    Computes per-campaign KPIs: CTR, CPC, ROAS, conversion_rate.

    Typical usage::

        pipeline = MarketingPipeline()
        result = pipeline.run(raw_ad_data)
        # or pull from Facebook:
        result = pipeline.run_from_facebook(account_id, access_token, date_range)
    """

    def __init__(self) -> None:
        self._cleaner = DataCleaner()
        self._normalizer = DataNormalizer()
        self._validator = DataValidator()
        self._feature_builder = FeatureBuilder()
        self._feature_store = FeatureStore()

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def run(self, raw_ad_data: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute the full marketing pipeline on *raw_ad_data*.

        Steps:
        1. Clean — whitespace strip, empty-record removal.
        2. Validate — check required fields and types.
        3. Normalize — date fields.
        4. Compute KPIs — CTR, CPC, ROAS, conversion_rate.
        5. Store features.

        Args:
            raw_ad_data: List of raw ad campaign dicts (from any platform).

        Returns:
            ``{
                "campaigns":  list[dict],
                "invalid":    list[dict],
                "stats": {
                    "total_input":  int,
                    "valid":        int,
                    "invalid":      int,
                    "total_spend":  float,
                    "total_clicks": int,
                    "total_impressions": int,
                    "blended_ctr":  float,
                    "duration_sec": float,
                }
            }``
        """
        start = time.monotonic()
        logger.info("MarketingPipeline.run: %d raw records", len(raw_ad_data))

        # Step 1: Clean
        cleaned = self._cleaner.clean(raw_ad_data)

        # Step 2: Validate
        valid, invalid = self._validator.validate(cleaned, _ADS_SCHEMA)

        # Step 3: Normalize
        normalized = self._normalizer.normalize(valid, _ADS_NORM_CONFIG)

        # Step 4: Compute KPIs per campaign
        campaigns = [_compute_ad_metrics(r) for r in normalized]

        # Step 5: Store
        self._feature_store.store("marketing_latest", campaigns)

        duration = round(time.monotonic() - start, 3)

        total_spend = sum(float(c.get("spend") or 0) for c in campaigns)
        total_clicks = sum(int(c.get("clicks") or 0) for c in campaigns)
        total_impressions = sum(int(c.get("impressions") or 0) for c in campaigns)
        blended_ctr = (
            round(total_clicks / total_impressions, 6) if total_impressions > 0 else 0.0
        )

        stats: dict[str, Any] = {
            "total_input": len(raw_ad_data),
            "valid": len(valid),
            "invalid": len(invalid),
            "total_spend": round(total_spend, 2),
            "total_clicks": total_clicks,
            "total_impressions": total_impressions,
            "blended_ctr": blended_ctr,
            "duration_sec": duration,
        }
        logger.info(
            "MarketingPipeline complete: %d campaigns, spend=%.2f, blended_ctr=%.4f",
            len(campaigns),
            total_spend,
            blended_ctr,
        )
        return {"campaigns": campaigns, "invalid": invalid, "stats": stats}

    # ------------------------------------------------------------------
    # Platform-specific entry points
    # ------------------------------------------------------------------

    def run_from_facebook(
        self,
        account_id: str,
        access_token: str,
        date_range: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch Facebook ad data and run the full pipeline.

        Args:
            account_id:   Meta ad-account ID.
            access_token: Meta access token.
            date_range:   ``{"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"}``.

        Returns:
            Same structure as :meth:`run`.
        """
        logger.info("MarketingPipeline: fetching Facebook Ads for account %s", account_id)
        api = AdsAPI()
        response = api.fetch_facebook_ads(account_id, access_token, date_range)
        campaigns = response.get("campaigns", [])
        if response.get("errors"):
            logger.warning("Facebook Ads errors: %s", response["errors"])
        return self.run(campaigns)

    def run_from_google(
        self,
        customer_id: str,
        credentials: dict[str, str],
        date_range: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch Google Ads data and run the full pipeline.

        Args:
            customer_id:  Google Ads customer ID.
            credentials:  ``{"developer_token": str, "access_token": str}``.
            date_range:   ``{"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"}``.

        Returns:
            Same structure as :meth:`run`.
        """
        logger.info("MarketingPipeline: fetching Google Ads for customer %s", customer_id)
        api = AdsAPI()
        response = api.fetch_google_ads(customer_id, credentials, date_range)
        campaigns = response.get("campaigns", [])
        if response.get("errors"):
            logger.warning("Google Ads errors: %s", response["errors"])
        return self.run(campaigns)
