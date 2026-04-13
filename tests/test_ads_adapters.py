"""Tests for Google Ads and Meta Ads adapters.

Real HTTP calls are forbidden — every test patches
``_http_request`` to return canned responses.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
        "META_ADS_ACCESS_TOKEN", "META_ADS_ACCOUNT_ID",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_google_ads(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "dev-token-123")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("GOOGLE_ADS_CUSTOMER_ID", "1234567890")
    get_config().reload()


def _configure_meta_ads(monkeypatch):
    monkeypatch.setenv("META_ADS_ACCESS_TOKEN", "EAABs...")
    monkeypatch.setenv("META_ADS_ACCOUNT_ID", "act_123456")
    get_config().reload()


# ── Google Ads ────────────────────────────────────────────


class TestGoogleAdsMetadata:
    def test_metadata(self):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        a = GoogleAdsAdapter()
        assert a.name == "google_ads"
        assert a.category == AdapterCategory.ADS
        assert Capability.ADS_CREATE_CAMPAIGN in a.capabilities
        assert Capability.ADS_GET_PERFORMANCE in a.capabilities
        assert Capability.ADS_UPDATE_BUDGET in a.capabilities
        assert a.priority == 85

    def test_unconfigured_without_keys(self):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        assert not GoogleAdsAdapter().is_configured()

    def test_configured_with_all_keys(self, monkeypatch):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        _configure_google_ads(monkeypatch)
        assert GoogleAdsAdapter().is_configured()

    def test_not_configured_missing_refresh_token(self, monkeypatch):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "t")
        monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "c")
        monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "s")
        monkeypatch.setenv("GOOGLE_ADS_CUSTOMER_ID", "123")
        get_config().reload()
        assert not GoogleAdsAdapter().is_configured()


class TestGoogleAdsPerformance:
    def test_get_performance(self, monkeypatch):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        _configure_google_ads(monkeypatch)
        a = GoogleAdsAdapter()

        raw_response = {
            "results": [{
                "campaign": {"name": "Summer Sale", "id": "123"},
                "metrics": {
                    "impressions": "5000",
                    "clicks": "250",
                    "costMicros": "15000000",
                    "conversions": "12",
                },
            }],
        }

        with patch.object(a, "_http_request", return_value=raw_response), \
             patch.object(a, "_get_access_token", return_value="access-tok"):
            result = a.execute(
                Capability.ADS_GET_PERFORMANCE,
                {"date_range": "LAST_7_DAYS"},
            )

        assert result.ok
        campaigns = result.data["campaigns"]
        assert len(campaigns) == 1
        assert campaigns[0]["campaign_name"] == "Summer Sale"
        assert campaigns[0]["cost"] == 15.0

    def test_create_campaign_requires_name(self, monkeypatch):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        _configure_google_ads(monkeypatch)
        a = GoogleAdsAdapter()

        with patch.object(a, "_get_access_token", return_value="tok"):
            result = a.execute(
                Capability.ADS_CREATE_CAMPAIGN,
                {"budget_amount_micros": 10000000},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_update_budget_requires_campaign_id(self, monkeypatch):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        _configure_google_ads(monkeypatch)
        a = GoogleAdsAdapter()

        with patch.object(a, "_get_access_token", return_value="tok"):
            result = a.execute(
                Capability.ADS_UPDATE_BUDGET,
                {"budget_amount_micros": 5000000},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Meta Ads ──────────────────────────────────────────────


class TestMetaAdsMetadata:
    def test_metadata(self):
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        a = MetaAdsAdapter()
        assert a.name == "meta_ads"
        assert a.category == AdapterCategory.ADS
        assert Capability.ADS_GET_PERFORMANCE in a.capabilities
        assert a.priority == 80

    def test_unconfigured_without_keys(self):
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        assert not MetaAdsAdapter().is_configured()

    def test_configured_with_keys(self, monkeypatch):
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        _configure_meta_ads(monkeypatch)
        assert MetaAdsAdapter().is_configured()


class TestMetaAdsPerformance:
    def test_get_performance(self, monkeypatch):
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        _configure_meta_ads(monkeypatch)
        a = MetaAdsAdapter()

        raw_response = {
            "data": [{
                "campaign_name": "Instagram Promo",
                "impressions": "10000",
                "reach": "8000",
                "spend": "50.00",
                "clicks": "500",
            }],
        }

        with patch.object(a, "_http_request", return_value=raw_response):
            result = a.execute(
                Capability.ADS_GET_PERFORMANCE, {},
            )

        assert result.ok
        campaigns = result.data["campaigns"]
        assert len(campaigns) == 1
        assert campaigns[0]["campaign_name"] == "Instagram Promo"
        assert campaigns[0]["spend"] == 50.0

    def test_create_campaign_requires_objective(self, monkeypatch):
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        _configure_meta_ads(monkeypatch)
        a = MetaAdsAdapter()

        result = a.execute(
            Capability.ADS_CREATE_CAMPAIGN,
            {"name": "Test Campaign"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_update_budget_requires_campaign_id(self, monkeypatch):
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        _configure_meta_ads(monkeypatch)
        a = MetaAdsAdapter()

        result = a.execute(
            Capability.ADS_UPDATE_BUDGET,
            {"daily_budget": 100},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Bootstrap ─────────────────────────────────────────────


class TestAdsBootstrap:
    def test_register_all(self):
        from core.adapters.ads.bootstrap import register_all
        status = register_all()
        assert "google_ads" in status
        assert "meta_ads" in status

    def test_unconfigured_without_keys(self):
        from core.adapters.ads.bootstrap import register_all
        status = register_all()
        assert status["google_ads"] is False
        assert status["meta_ads"] is False

    def test_router_picks_google_ads_when_configured(self, monkeypatch):
        from core.adapters.ads.bootstrap import register_all
        _configure_google_ads(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.ADS_GET_PERFORMANCE)
        assert chosen.name == "google_ads"
