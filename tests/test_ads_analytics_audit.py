"""Tests for audit-pass-46 fixes — defensive + retry hardening
across ``data_pipeline.ingestion.api.ads_api`` and
``analytics_api``.

Both files had the same bug patterns the Shopify client
audit (pass 43) fixed:

  * ``float(resp.headers.get("Retry-After"))`` crashed on
    RFC 7231 HTTP-date form (pre-audit all three ad
    platforms shared the bug).
  * Google Ads had NO retry logic at all — a single 429 /
    5xx / network blip lost the entire request.
  * Bare ``int()`` / ``float()`` on API response metrics
    crashed on non-numeric strings like ``"$10.50"``,
    ``"1,000"``, or ``None`` from real API responses.
  * ``.get(k, {}).get(...)`` / ``.get(k, [])`` chains
    crashed on present-but-None sub-fields (same pattern as
    passes 32/36/40/41/42/43/45).
  * No defensive coercion on any public entry point — None
    credentials / None date_range crashed immediately.

``analytics_api.py`` additionally had:

  * ``_safe_post`` / ``_safe_get`` had NO retry logic.
  * GA4 ``_safe_post`` → parse path crashed on null
    ``dimensionHeaders`` / ``metricHeaders`` / ``rows``.
  * ``int(count)`` on a Mixpanel count crashed on non-
    numeric values.
"""
from __future__ import annotations

from unittest import mock

import pytest

from data_pipeline.ingestion.api.ads_api import AdsAPI, _empty_record
from data_pipeline.ingestion.api.analytics_api import (
    AnalyticsAPI,
    _default_date_range,
    _ensure_date_range,
)


# ═══════════════════════════════════════════════════════════
# AdsAPI — defensive entry coercion
# ═══════════════════════════════════════════════════════════


class TestAdsAPIDefensive:
    def test_fetch_facebook_ads_none_args(self):
        a = AdsAPI()
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_get",
            return_value={"_error": "mock"},
        ):
            r = a.fetch_facebook_ads(None, None, None)
        assert r["platform"] == "facebook"
        assert r["errors"] == ["mock"]
        assert r["campaigns"] == []

    def test_fetch_google_ads_none_args(self):
        a = AdsAPI()
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_post",
            return_value={"_error": "mock"},
        ):
            r = a.fetch_google_ads(None, None, None)
        assert r["platform"] == "google"
        assert r["errors"] == ["mock"]

    def test_fetch_tiktok_ads_none_args(self):
        a = AdsAPI()
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_get",
            return_value={"_error": "mock"},
        ):
            r = a.fetch_tiktok_ads(None, None, None)
        assert r["platform"] == "tiktok"

    def test_ensure_date_range_non_dict(self):
        r = AdsAPI._ensure_date_range(None, 30)
        assert "since" in r and "until" in r

    def test_ensure_date_range_missing_keys(self):
        r = AdsAPI._ensure_date_range({"since": None, "until": None}, 30)
        assert isinstance(r["since"], str)
        assert isinstance(r["until"], str)

    def test_ensure_date_range_preserves_valid(self):
        r = AdsAPI._ensure_date_range(
            {"since": "2024-01-01", "until": "2024-01-31"}, 30
        )
        assert r == {"since": "2024-01-01", "until": "2024-01-31"}


# ═══════════════════════════════════════════════════════════
# Facebook Ads response parsing
# ═══════════════════════════════════════════════════════════


class TestFacebookParse:
    def test_non_numeric_spend_does_not_crash(self):
        """Pre-audit ``float(item.get("spend", 0.0))`` crashed
        on strings like ``"$10.50"``."""
        a = AdsAPI()
        fake = {
            "data": [
                {
                    "campaign_id": "c1",
                    "impressions": "1000",
                    "clicks": "50",
                    "spend": "$10.50",
                    "campaign_name": "test",
                },
            ],
        }
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_get",
            return_value=fake,
        ):
            r = a.fetch_facebook_ads("act_1", "tok")
        assert len(r["campaigns"]) == 1
        assert r["campaigns"][0]["spend"] == 10.5
        assert r["campaigns"][0]["impressions"] == 1000

    def test_null_data_field(self):
        """Present-but-None ``data`` field doesn't crash."""
        a = AdsAPI()
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_get",
            return_value={"data": None},
        ):
            r = a.fetch_facebook_ads("act_1", "tok")
        assert r["campaigns"] == []

    def test_non_dict_items_skipped(self):
        a = AdsAPI()
        fake = {
            "data": [
                None,
                "not a dict",
                {"campaign_id": "good", "impressions": "5"},
            ],
        }
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_get",
            return_value=fake,
        ):
            r = a.fetch_facebook_ads("act_1", "tok")
        assert len(r["campaigns"]) == 1
        assert r["campaigns"][0]["campaign_id"] == "good"

    def test_null_actions_array(self):
        """``actions: null`` crashed ``for action in None``."""
        a = AdsAPI()
        fake = {
            "data": [
                {"campaign_id": "c1", "actions": None},
            ],
        }
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_get",
            return_value=fake,
        ):
            r = a.fetch_facebook_ads("act_1", "tok")
        assert r["campaigns"][0]["conversions"] == 0

    def test_fb_extract_conversions_handles_none(self):
        assert AdsAPI._fb_extract_conversions(None) == 0
        assert AdsAPI._fb_extract_conversions("not a list") == 0

    def test_fb_extract_conversions_sums_purchase(self):
        actions = [
            {"action_type": "purchase", "value": "5"},
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"},
            {"action_type": "other", "value": "99"},  # ignored
            {"action_type": "omni_purchase", "value": "2"},
        ]
        assert AdsAPI._fb_extract_conversions(actions) == 10

    def test_fb_extract_conversions_skips_non_dict(self):
        actions = ["bad", None, {"action_type": "purchase", "value": "1"}]
        assert AdsAPI._fb_extract_conversions(actions) == 1


# ═══════════════════════════════════════════════════════════
# Google Ads response parsing
# ═══════════════════════════════════════════════════════════


class TestGoogleAdsParse:
    def test_non_numeric_cost_micros(self):
        a = AdsAPI()
        fake = {
            "results": [
                {
                    "campaign": {"id": "123", "name": "test"},
                    "metrics": {
                        "impressions": "1000",
                        "clicks": "50",
                        "costMicros": "12345678",  # 12.35 after micros
                        "conversions": "3.0",
                    },
                },
            ],
        }
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_post",
            return_value=fake,
        ):
            r = a.fetch_google_ads("123", {"access_token": "t"})
        assert len(r["campaigns"]) == 1
        c = r["campaigns"][0]
        assert c["impressions"] == 1000
        assert c["spend"] == 12.35
        assert c["conversions"] == 3

    def test_null_campaign_or_metrics(self):
        a = AdsAPI()
        fake = {
            "results": [
                {"campaign": None, "metrics": None},
                {"campaign": {"id": "2"}, "metrics": {}},
            ],
        }
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_post",
            return_value=fake,
        ):
            r = a.fetch_google_ads("123", {"access_token": "t"})
        assert len(r["campaigns"]) == 2

    def test_null_results_field(self):
        a = AdsAPI()
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_post",
            return_value={"results": None},
        ):
            r = a.fetch_google_ads("123", {"access_token": "t"})
        assert r["campaigns"] == []


# ═══════════════════════════════════════════════════════════
# TikTok Ads response parsing
# ═══════════════════════════════════════════════════════════


class TestTikTokParse:
    def test_non_numeric_metrics(self):
        a = AdsAPI()
        fake = {
            "data": {
                "list": [
                    {
                        "dimensions": {"campaign_id": "c1"},
                        "metrics": {
                            "impressions": "1000",
                            "clicks": "50",
                            "spend": "$15.50",
                            "conversions": "2",
                            "campaign_name": "t",
                        },
                    },
                ],
            },
        }
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_get",
            return_value=fake,
        ):
            r = a.fetch_tiktok_ads("adv1", "tok")
        assert len(r["campaigns"]) == 1
        assert r["campaigns"][0]["spend"] == 15.5

    def test_null_data_block(self):
        """Present-but-None ``data`` field doesn't crash the
        chained ``.get("list")``."""
        a = AdsAPI()
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_get",
            return_value={"data": None},
        ):
            r = a.fetch_tiktok_ads("adv1", "tok")
        assert r["campaigns"] == []

    def test_null_list_field(self):
        a = AdsAPI()
        with mock.patch(
            "data_pipeline.ingestion.api.ads_api._safe_get",
            return_value={"data": {"list": None}},
        ):
            r = a.fetch_tiktok_ads("adv1", "tok")
        assert r["campaigns"] == []


# ═══════════════════════════════════════════════════════════
# AnalyticsAPI — GA4 parsing
# ═══════════════════════════════════════════════════════════


class TestGA4Parse:
    def test_none_headers_and_rows(self):
        """Present-but-None ``dimensionHeaders`` / ``rows``
        crashed the list comprehension."""
        a = AnalyticsAPI()
        fake = {"dimensionHeaders": None, "metricHeaders": None, "rows": None}
        with mock.patch(
            "data_pipeline.ingestion.api.analytics_api._safe_post",
            return_value=fake,
        ):
            r = a.fetch_google_analytics("prop1", {"access_token": "t"})
        assert r["records"] == []
        assert r["errors"] == []

    def test_none_credentials(self):
        a = AnalyticsAPI()
        with mock.patch(
            "data_pipeline.ingestion.api.analytics_api._safe_post",
            return_value={"_error": "mock"},
        ):
            r = a.fetch_google_analytics("prop1", None)
        assert r["errors"] == ["mock"]

    def test_non_dict_val(self):
        """``val.get("value")`` crashed on non-dict val."""
        a = AnalyticsAPI()
        fake = {
            "dimensionHeaders": [{"name": "date"}],
            "metricHeaders": [{"name": "sessions"}],
            "rows": [
                {
                    "dimensionValues": ["not a dict"],
                    "metricValues": [None],
                },
                {
                    "dimensionValues": [{"value": "2024-01-01"}],
                    "metricValues": [{"value": "100"}],
                },
            ],
        }
        with mock.patch(
            "data_pipeline.ingestion.api.analytics_api._safe_post",
            return_value=fake,
        ):
            r = a.fetch_google_analytics("prop1", {"access_token": "t"})
        # One good row + one partially-parsed row
        assert len(r["records"]) == 2
        assert r["records"][1]["date"] == "2024-01-01"
        assert r["records"][1]["sessions"] == 100.0

    def test_non_numeric_metric_preserved(self):
        a = AnalyticsAPI()
        fake = {
            "dimensionHeaders": [],
            "metricHeaders": [{"name": "sessions"}],
            "rows": [
                {
                    "dimensionValues": [],
                    "metricValues": [{"value": "N/A"}],
                },
            ],
        }
        with mock.patch(
            "data_pipeline.ingestion.api.analytics_api._safe_post",
            return_value=fake,
        ):
            r = a.fetch_google_analytics("prop1", {"access_token": "t"})
        assert len(r["records"]) == 1
        # "N/A" is preserved as string since safe_float
        # returns NaN sentinel for garbage.
        assert r["records"][0]["sessions"] == "N/A"

    def test_non_list_metrics_arg_falls_back(self):
        a = AnalyticsAPI()
        with mock.patch(
            "data_pipeline.ingestion.api.analytics_api._safe_post",
            return_value={"_error": "mock"},
        ):
            r = a.fetch_google_analytics("prop1", {"access_token": "t"}, metrics="not a list")  # type: ignore[arg-type]
        assert r["errors"] == ["mock"]


# ═══════════════════════════════════════════════════════════
# AnalyticsAPI — Mixpanel parsing
# ═══════════════════════════════════════════════════════════


class TestMixpanelParse:
    def test_none_data_block(self):
        a = AnalyticsAPI()
        with mock.patch(
            "data_pipeline.ingestion.api.analytics_api._safe_get",
            return_value={"data": None},
        ):
            r = a.fetch_mixpanel("proj1", "sec")
        assert r["records"] == []

    def test_non_numeric_count(self):
        """Pre-audit ``int(count)`` crashed on string counts."""
        a = AnalyticsAPI()
        fake = {
            "data": {
                "series": ["2024-01-01", "2024-01-02"],
                "values": {
                    "signup": {"2024-01-01": "5", "2024-01-02": "bad"},
                },
            },
        }
        with mock.patch(
            "data_pipeline.ingestion.api.analytics_api._safe_get",
            return_value=fake,
        ):
            r = a.fetch_mixpanel("proj1", "sec")
        assert len(r["records"]) == 2
        assert r["records"][0]["count"] == 5
        # Bad count silently coerced to 0, not a crash.
        assert r["records"][1]["count"] == 0

    def test_non_dict_date_counts_skipped(self):
        a = AnalyticsAPI()
        fake = {
            "data": {
                "series": ["2024-01-01"],
                "values": {
                    "broken": "not a dict",
                    "good": {"2024-01-01": 42},
                },
            },
        }
        with mock.patch(
            "data_pipeline.ingestion.api.analytics_api._safe_get",
            return_value=fake,
        ):
            r = a.fetch_mixpanel("proj1", "sec")
        # Only the "good" event is recorded.
        assert len(r["records"]) == 1
        assert r["records"][0]["event"] == "good"
        assert r["records"][0]["count"] == 42


# ═══════════════════════════════════════════════════════════
# Date range helpers
# ═══════════════════════════════════════════════════════════


class TestDateRangeHelpers:
    def test_default_date_range_negative_days(self):
        r = _default_date_range(-5)
        assert "since" in r and "until" in r

    def test_ensure_date_range_none(self):
        r = _ensure_date_range(None, 30)
        assert "since" in r and "until" in r

    def test_ensure_date_range_non_string_values(self):
        r = _ensure_date_range({"since": 42, "until": None}, 30)
        assert isinstance(r["since"], str)
        assert isinstance(r["until"], str)

    def test_ensure_date_range_preserves_valid(self):
        r = _ensure_date_range({"since": "2024-01-01", "until": "2024-01-31"}, 30)
        assert r == {"since": "2024-01-01", "until": "2024-01-31"}
