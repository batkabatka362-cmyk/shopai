"""AnalyticsPipeline — ingests, cleans, and feature-engineers web analytics data."""
from __future__ import annotations

import logging
import time
from typing import Any

from data_pipeline.processing.cleaner import DataCleaner
from data_pipeline.processing.normalizer import DataNormalizer
from data_pipeline.processing.validator import DataValidator
from data_pipeline.feature_engineering.feature_builder import FeatureBuilder
from data_pipeline.feature_engineering.feature_store import FeatureStore
from data_pipeline.ingestion.api.analytics_api import AnalyticsAPI
from utils.helpers import safe_float

logger = logging.getLogger("data_pipeline.analytics_pipeline")

# Validation schema
_ANALYTICS_SCHEMA: dict[str, Any] = {
    "required": [],  # analytics records vary widely; only basic types enforced
    "types": {
        "sessions": "float",
        "bounceRate": "float",
        "screenPageViews": "float",
        "totalRevenue": "float",
    },
    "ranges": {
        "bounceRate": {"min": 0.0, "max": 1.0},
        "sessions": {"min": 0.0},
    },
}

_ANALYTICS_NORM_CONFIG: dict[str, Any] = {
    "date_fields": ["date"],
}


def _compute_analytics_metrics(record: dict[str, Any]) -> dict[str, Any]:
    """Compute derived analytics metrics for a single session record.

    Adds:
    * ``session_value``           — revenue per session.
    * ``bounce_rate_normalized``  — bounce rate already in [0,1]; kept as-is,
                                    but clamped and rounded.
    * ``page_depth_score``        — log(1 + pages_per_session) for a smooth scale.
    """
    import math

    if not isinstance(record, dict):
        return {}
    rec = dict(record)

    # Pre-audit bare float() crashed on non-numeric strings
    # from GA4 / Mixpanel. Audit pass 50.
    sessions = safe_float(rec.get("sessions"))
    revenue = safe_float(rec.get("totalRevenue"))
    bounce_rate = safe_float(rec.get("bounceRate"))
    page_views = safe_float(rec.get("screenPageViews"))

    # session_value: revenue per session
    rec["session_value"] = round(revenue / sessions, 4) if sessions > 0 else 0.0

    # bounce_rate_normalized: clamp to [0, 1]
    rec["bounce_rate_normalized"] = round(max(0.0, min(1.0, bounce_rate)), 4)

    # page_depth_score: pages per session, log-scaled
    pages_per_session = (page_views / sessions) if sessions > 0 else 0.0
    rec["page_depth_score"] = round(math.log1p(pages_per_session), 4)

    return rec


class AnalyticsPipeline:
    """Raw → Clean → Validate → Normalize → Feature engineer for analytics data.

    Computes per-session KPIs: session_value, bounce_rate_normalized,
    page_depth_score.

    Typical usage::

        pipeline = AnalyticsPipeline()
        result = pipeline.run(raw_analytics)
        # or pull from GA4:
        result = pipeline.run_from_google_analytics(property_id, credentials, date_range)
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

    def run(self, raw_analytics: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute the full analytics pipeline on *raw_analytics*.

        Steps:
        1. Clean — strip whitespace, remove empty records.
        2. Validate — basic type and range checks.
        3. Normalize — date fields; bounce rate as float.
        4. Compute KPIs — session_value, bounce_rate_normalized, page_depth_score.
        5. Store features.

        Args:
            raw_analytics: List of raw analytics records (rows from GA4, Mixpanel, etc.).

        Returns:
            ``{
                "records":  list[dict],
                "invalid":  list[dict],
                "stats": {
                    "total_input":        int,
                    "valid":              int,
                    "invalid":            int,
                    "total_sessions":     float,
                    "total_revenue":      float,
                    "avg_session_value":  float,
                    "avg_bounce_rate":    float,
                    "duration_sec":       float,
                }
            }``
        """
        start = time.monotonic()
        # Defensive: coerce None / non-list at entry so
        # ``len(raw_analytics)`` can't crash. Audit pass 50.
        if not isinstance(raw_analytics, list):
            raw_analytics = []
        logger.info("AnalyticsPipeline.run: %d raw records", len(raw_analytics))

        # Step 1: Clean
        cleaned = self._cleaner.clean(raw_analytics)

        # Step 2: Validate
        valid, invalid = self._validator.validate(cleaned, _ANALYTICS_SCHEMA)

        # Step 3: Normalize
        normalized = self._normalizer.normalize(valid, _ANALYTICS_NORM_CONFIG)

        # Step 4: Compute KPIs
        records = [_compute_analytics_metrics(r) for r in normalized if isinstance(r, dict)]

        # Step 5: Store
        self._feature_store.store("analytics_latest", records)

        duration = round(time.monotonic() - start, 3)

        total_sessions = sum(safe_float(r.get("sessions")) for r in records)
        total_revenue = sum(safe_float(r.get("totalRevenue")) for r in records)
        avg_session_value = (
            round(total_revenue / total_sessions, 4) if total_sessions > 0 else 0.0
        )
        bounce_rates = [safe_float(r.get("bounce_rate_normalized")) for r in records]
        avg_bounce_rate = (
            round(sum(bounce_rates) / len(bounce_rates), 4) if bounce_rates else 0.0
        )

        stats: dict[str, Any] = {
            "total_input": len(raw_analytics),
            "valid": len(valid),
            "invalid": len(invalid),
            "total_sessions": round(total_sessions, 2),
            "total_revenue": round(total_revenue, 2),
            "avg_session_value": avg_session_value,
            "avg_bounce_rate": avg_bounce_rate,
            "duration_sec": duration,
        }
        logger.info(
            "AnalyticsPipeline complete: %d records, sessions=%.0f, avg_session_value=%.4f",
            len(records),
            total_sessions,
            avg_session_value,
        )
        return {"records": records, "invalid": invalid, "stats": stats}

    # ------------------------------------------------------------------
    # Platform-specific entry points
    # ------------------------------------------------------------------

    def run_from_google_analytics(
        self,
        property_id: str,
        credentials: dict[str, str],
        date_range: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch GA4 data and run the full pipeline.

        Args:
            property_id:  GA4 property ID (e.g. ``"123456789"``).
            credentials:  ``{"access_token": str}``.
            date_range:   ``{"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"}``.

        Returns:
            Same structure as :meth:`run`.
        """
        logger.info(
            "AnalyticsPipeline: fetching GA4 data for property %s", property_id
        )
        api = AnalyticsAPI()
        response = api.fetch_google_analytics(property_id, credentials, date_range=date_range)
        records = response.get("records", [])
        if response.get("errors"):
            logger.warning("GA4 errors: %s", response["errors"])
        return self.run(records)
