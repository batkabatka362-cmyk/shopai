"""Mock-HTTP regression for TikTokAdsAdapter."""
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
from core.adapters.errors import AdapterError


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "TIKTOK_ADS_ACCESS_TOKEN",
        "TIKTOK_ADS_ADVERTISER_ID",
        "SHOPAI_TIKTOK_ADS_API_VERSION",
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


def _configure(monkeypatch):
    monkeypatch.setenv(
        "TIKTOK_ADS_ACCESS_TOKEN", "t" * 40,
    )
    monkeypatch.setenv(
        "TIKTOK_ADS_ADVERTISER_ID", "123456789",
    )
    get_config().reload()


# ── Metadata ────────────────────────────────────────────────


class TestMetadata:
    def test_name_and_category(self):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        a = TikTokAdsAdapter()
        assert a.name == "tiktok_ads"
        assert a.category == AdapterCategory.ADS
        assert Capability.ADS_CREATE_CAMPAIGN in a.capabilities
        assert Capability.ADS_UPDATE_BUDGET in a.capabilities
        assert Capability.ADS_PAUSE_CAMPAIGN in a.capabilities
        assert Capability.ADS_RESUME_CAMPAIGN in a.capabilities
        assert Capability.ADS_GET_PERFORMANCE in a.capabilities
        assert a.priority == 75

    def test_base_url_default_version(self):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        a = TikTokAdsAdapter()
        assert (
            a.base_url
            == "https://business-api.tiktok.com/open_api/v1.3"
        )

    def test_base_url_env_override(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        monkeypatch.setenv(
            "SHOPAI_TIKTOK_ADS_API_VERSION", "v1.5",
        )
        a = TikTokAdsAdapter()
        assert a.base_url.endswith("/open_api/v1.5")


# ── Configuration ──────────────────────────────────────────


class TestConfiguration:
    def test_unconfigured_without_token(self):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        assert not TikTokAdsAdapter().is_configured()

    def test_unconfigured_without_advertiser_id(
        self, monkeypatch,
    ):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        monkeypatch.setenv(
            "TIKTOK_ADS_ACCESS_TOKEN", "t" * 40,
        )
        get_config().reload()
        assert not TikTokAdsAdapter().is_configured()

    def test_configured_with_both(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        assert TikTokAdsAdapter().is_configured()


# ── create_campaign ────────────────────────────────────────


class TestCreateCampaign:
    def test_requires_name(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()
        res = a.execute(
            Capability.ADS_CREATE_CAMPAIGN,
            {"budget": 20.0},
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_requires_positive_budget(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()
        res = a.execute(
            Capability.ADS_CREATE_CAMPAIGN,
            {"name": "Launch", "budget": 0},
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_creates_paused_by_default(self, monkeypatch):
        """Paranoid mode (§4b.G) — live money never spends
        without an explicit resume call after."""
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["method"] = method
            captured["path"] = path
            captured["body"] = body
            return {
                "code": 0,
                "message": "OK",
                "data": {"campaign_id": "C-1"},
            }

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_CREATE_CAMPAIGN,
                {
                    "name": "Spring Launch",
                    "budget": 25.5,
                    "objective": "conversions",
                },
            )
        assert res.ok
        assert res.data["campaign_id"] == "C-1"
        assert res.data["status"] == "DISABLE"
        assert captured["path"] == "/campaign/create/"
        body = captured["body"]
        assert body["campaign_name"] == "Spring Launch"
        assert body["objective_type"] == "CONVERSIONS"
        assert body["budget"] == 25.5
        assert body["operation_status"] == "DISABLE"
        assert body["advertiser_id"] == "123456789"

    def test_tiktok_code_nonzero_raises_adapter_error(
        self, monkeypatch,
    ):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()

        def fake_http(method, url, body=None):
            return {
                "code": 40002,
                "message": "parameter error",
                "data": {},
            }

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            res = a.execute(
                Capability.ADS_CREATE_CAMPAIGN,
                {"name": "x", "budget": 5},
            )
        assert not res.ok
        assert isinstance(res.error, AdapterError)
        assert "40002" in res.error.reason


# ── update_budget ──────────────────────────────────────────


class TestUpdateBudget:
    def test_requires_campaign_id(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()
        res = a.execute(
            Capability.ADS_UPDATE_BUDGET, {"budget": 10},
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_happy_path(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["body"] = body
            return {"code": 0, "data": {}}

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_UPDATE_BUDGET,
                {"campaign_id": "C-1", "budget": 30},
            )
        assert res.ok
        body = captured["body"]
        assert body["campaign_id"] == "C-1"
        assert body["budget"] == 30.0


# ── pause / resume ─────────────────────────────────────────


class TestStatusToggle:
    def test_pause(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured.update({"path": path, "body": body})
            return {"code": 0, "data": {}}

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_PAUSE_CAMPAIGN,
                {"campaign_id": "C-1"},
            )
        assert res.ok
        assert captured["path"] == "/campaign/status/update/"
        assert captured["body"]["operation_status"] == "DISABLE"
        assert captured["body"]["campaign_ids"] == ["C-1"]
        assert res.data["status"] == "DISABLE"

    def test_resume(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["body"] = body
            return {"code": 0, "data": {}}

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_RESUME_CAMPAIGN,
                {"campaign_id": "C-1"},
            )
        assert res.ok
        assert captured["body"]["operation_status"] == "ENABLE"


# ── performance ────────────────────────────────────────────


class TestPerformance:
    def test_requires_dates(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()
        res = a.execute(
            Capability.ADS_GET_PERFORMANCE,
            {"campaign_id": "C-1"},
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_happy_path(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured.update({"path": path, "params": params})
            return {
                "code": 0,
                "data": {"list": [{
                    "metrics": {
                        "spend": "25.50",
                        "impressions": "10000",
                        "clicks": "250",
                        "ctr": "2.5",
                        "conversion": "7",
                        "cost_per_conversion": "3.64",
                        "cpc": "0.10",
                    },
                }]},
            }

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_GET_PERFORMANCE,
                {
                    "campaign_id": "C-1",
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-24",
                },
            )
        assert res.ok
        assert captured["path"] == "/report/integrated/get/"
        m = res.data["metrics"]
        assert m["spend"] == "25.50"
        assert m["conversion"] == "7"

    def test_empty_rows_returns_zero_metrics(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()

        def fake_request(method, path, *, body=None, params=None):
            return {"code": 0, "data": {"list": []}}

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_GET_PERFORMANCE,
                {
                    "campaign_id": "C-1",
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-24",
                },
            )
        assert res.ok
        assert res.data["metrics"] == {}


# ── URL query encoding ─────────────────────────────────────


class TestUrlEncoding:
    def test_get_params_are_url_encoded(self, monkeypatch):
        from core.adapters.ads.tiktok_ads import TikTokAdsAdapter
        _configure(monkeypatch)
        a = TikTokAdsAdapter()
        captured = {}

        def fake_http(method, url, body=None):
            captured["url"] = url
            return {"code": 0, "data": {"list": []}}

        with patch.object(
            a, "_http_request", side_effect=fake_http,
        ):
            a.execute(
                Capability.ADS_GET_PERFORMANCE,
                {
                    "campaign_id": "C-1",
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-24",
                },
            )
        url = captured["url"]
        assert "advertiser_id=123456789" in url
        assert "start_date=2026-04-01" in url
        assert "end_date=2026-04-24" in url


# ── Bootstrap + router ─────────────────────────────────────


class TestBootstrap:
    def test_tiktok_registered(self):
        from core.adapters.ads.bootstrap import register_all
        status = register_all()
        assert "tiktok_ads" in status

    def test_configured_when_env_set(self, monkeypatch):
        from core.adapters.ads.bootstrap import register_all
        _configure(monkeypatch)
        status = register_all()
        assert status["tiktok_ads"] is True

    def test_meta_wins_tie_when_both_configured(
        self, monkeypatch,
    ):
        """Meta priority 80 > TikTok 75 — Meta wins the tie."""
        from core.adapters.ads.bootstrap import register_all
        _configure(monkeypatch)
        monkeypatch.setenv(
            "META_ADS_ACCESS_TOKEN", "m" * 40,
        )
        monkeypatch.setenv(
            "META_ADS_ACCOUNT_ID", "act_999",
        )
        get_config().reload()
        register_all()
        chosen = get_router().route(
            Capability.ADS_CREATE_CAMPAIGN,
        )
        assert chosen.name == "meta_ads"

    def test_tiktok_chosen_when_only_tiktok_configured(
        self, monkeypatch,
    ):
        from core.adapters.ads.bootstrap import register_all
        _configure(monkeypatch)
        register_all()
        chosen = get_router().route(
            Capability.ADS_CREATE_CAMPAIGN,
        )
        assert chosen.name == "tiktok_ads"
