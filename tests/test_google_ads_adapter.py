"""Mock-HTTP regression for GoogleAdsAdapter."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
        "SHOPAI_GOOGLE_ADS_API_VERSION",
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
        "GOOGLE_ADS_DEVELOPER_TOKEN", "d" * 24,
    )
    monkeypatch.setenv(
        "GOOGLE_ADS_CLIENT_ID", "12345.apps.google.com",
    )
    monkeypatch.setenv(
        "GOOGLE_ADS_CLIENT_SECRET", "shh",
    )
    monkeypatch.setenv(
        "GOOGLE_ADS_REFRESH_TOKEN", "1//refresh",
    )
    monkeypatch.setenv(
        "GOOGLE_ADS_CUSTOMER_ID", "123-456-7890",
    )
    get_config().reload()


def _adapter(monkeypatch):
    from core.adapters.ads.google_ads import GoogleAdsAdapter
    _configure(monkeypatch)
    a = GoogleAdsAdapter()
    # Short-circuit OAuth refresh for every test.
    a._cached_access_token = "ya29-test"
    import time as _t
    a._token_expires_at = _t.monotonic() + 3600
    return a


# ── Metadata ─────────────────────────────────────────────


class TestMetadata:
    def test_name_and_category(self):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        a = GoogleAdsAdapter()
        assert a.name == "google_ads"
        assert a.category == AdapterCategory.ADS
        assert a.priority == 70
        for cap in (
            Capability.ADS_CREATE_CAMPAIGN,
            Capability.ADS_UPDATE_BUDGET,
            Capability.ADS_PAUSE_CAMPAIGN,
            Capability.ADS_RESUME_CAMPAIGN,
            Capability.ADS_GET_PERFORMANCE,
        ):
            assert cap in a.capabilities

    def test_base_url_versioned(self):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        a = GoogleAdsAdapter()
        assert "googleads.googleapis.com/v18" in a.base_url

    def test_api_version_override(self, monkeypatch):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        monkeypatch.setenv(
            "SHOPAI_GOOGLE_ADS_API_VERSION", "v19",
        )
        assert GoogleAdsAdapter().base_url.endswith("/v19")


# ── Configuration ────────────────────────────────────────


class TestConfiguration:
    def test_unconfigured_when_any_missing(self, monkeypatch):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        for key in (
            "GOOGLE_ADS_DEVELOPER_TOKEN",
            "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET",
            "GOOGLE_ADS_REFRESH_TOKEN",
            "GOOGLE_ADS_CUSTOMER_ID",
        ):
            # Reset, set everything-but-this.
            reset_config()
            for k2 in (
                "GOOGLE_ADS_DEVELOPER_TOKEN",
                "GOOGLE_ADS_CLIENT_ID",
                "GOOGLE_ADS_CLIENT_SECRET",
                "GOOGLE_ADS_REFRESH_TOKEN",
                "GOOGLE_ADS_CUSTOMER_ID",
            ):
                if k2 != key:
                    monkeypatch.setenv(k2, "x" * 10)
                else:
                    monkeypatch.delenv(k2, raising=False)
            get_config().reload()
            assert not GoogleAdsAdapter().is_configured(), (
                f"should be unconfigured when {key} missing"
            )

    def test_configured_when_all_set(self, monkeypatch):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        _configure(monkeypatch)
        assert GoogleAdsAdapter().is_configured()


# ── Customer id strips dashes ────────────────────────────


class TestCustomerIdNormalisation:
    def test_dashes_stripped(self, monkeypatch):
        a = _adapter(monkeypatch)
        assert a._customer_id() == "1234567890"


# ── create_campaign (two-step) ───────────────────────────


class TestCreateCampaign:
    def test_requires_name(self, monkeypatch):
        a = _adapter(monkeypatch)
        res = a.execute(
            Capability.ADS_CREATE_CAMPAIGN,
            {"budget": 25.0},
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_requires_positive_budget(self, monkeypatch):
        a = _adapter(monkeypatch)
        res = a.execute(
            Capability.ADS_CREATE_CAMPAIGN,
            {"name": "Launch", "budget": 0},
        )
        assert not res.ok
        assert isinstance(res.error, AdapterValidationError)

    def test_happy_path_creates_paused_with_budget(
        self, monkeypatch,
    ):
        a = _adapter(monkeypatch)
        calls: list[dict] = []

        def fake_request(method, path, *, body=None, params=None):
            calls.append({
                "method": method, "path": path, "body": body,
            })
            if "campaignBudgets:mutate" in path:
                return {
                    "results": [{
                        "resourceName":
                            "customers/1234567890/"
                            "campaignBudgets/99",
                    }],
                }
            if "campaigns:mutate" in path:
                return {
                    "results": [{
                        "resourceName":
                            "customers/1234567890/"
                            "campaigns/42",
                    }],
                }
            raise AssertionError(f"unexpected path {path}")

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_CREATE_CAMPAIGN,
                {"name": "Spring Launch", "budget": 25.5},
            )
        assert res.ok
        # Budget first, then campaign.
        assert len(calls) == 2
        assert "campaignBudgets:mutate" in calls[0]["path"]
        assert "campaigns:mutate" in calls[1]["path"]
        # Budget body uses micros.
        budget_op = calls[0]["body"]["operations"][0]["create"]
        assert budget_op["amount_micros"] == "25500000"
        # Campaign body references the budget resource and is
        # hard-forced to PAUSED.
        camp_op = calls[1]["body"]["operations"][0]["create"]
        assert camp_op["status"] == "PAUSED"
        assert camp_op["campaign_budget"] == (
            "customers/1234567890/campaignBudgets/99"
        )
        # Returned data carries both resources + status.
        assert res.data["status"] == "PAUSED"
        assert res.data["campaign_id"] == "42"
        assert res.data["budget_micros"] == 25500000

    def test_paused_is_immutable_via_params(self, monkeypatch):
        """Even if a caller tries to sneak a status field
        through params, the adapter still sends PAUSED."""
        a = _adapter(monkeypatch)

        def fake_request(method, path, *, body=None, params=None):
            if "campaignBudgets:mutate" in path:
                return {
                    "results": [{
                        "resourceName":
                            "customers/x/campaignBudgets/1",
                    }],
                }
            sent_status = (
                body["operations"][0]["create"]["status"]
            )
            assert sent_status == "PAUSED"
            return {
                "results": [{
                    "resourceName":
                        "customers/x/campaigns/9",
                }],
            }

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_CREATE_CAMPAIGN,
                {
                    "name": "x",
                    "budget": 10,
                    "status": "ENABLED",  # ignored
                },
            )
        assert res.ok
        assert res.data["status"] == "PAUSED"


# ── update_budget ────────────────────────────────────────


class TestUpdateBudget:
    def test_requires_budget_resource(self, monkeypatch):
        a = _adapter(monkeypatch)
        res = a.execute(
            Capability.ADS_UPDATE_BUDGET, {"budget": 20},
        )
        assert not res.ok

    def test_happy_path(self, monkeypatch):
        a = _adapter(monkeypatch)
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["body"] = body
            return {"results": [{"resourceName": "customers/x/campaignBudgets/99"}]}

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_UPDATE_BUDGET,
                {
                    "budget_resource":
                        "customers/1234567890/"
                        "campaignBudgets/99",
                    "budget": 40.0,
                },
            )
        assert res.ok
        op = captured["body"]["operations"][0]
        assert op["update"]["amount_micros"] == "40000000"
        assert op["updateMask"] == "amount_micros"


# ── pause / resume ───────────────────────────────────────


class TestStatusToggle:
    def test_pause(self, monkeypatch):
        a = _adapter(monkeypatch)
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["body"] = body
            return {"results": [{"resourceName": "x"}]}

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_PAUSE_CAMPAIGN,
                {"campaign_resource":
                 "customers/x/campaigns/1"},
            )
        assert res.ok
        op = captured["body"]["operations"][0]
        assert op["update"]["status"] == "PAUSED"
        assert op["updateMask"] == "status"

    def test_resume(self, monkeypatch):
        a = _adapter(monkeypatch)
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["body"] = body
            return {"results": [{"resourceName": "x"}]}

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_RESUME_CAMPAIGN,
                {"campaign_resource":
                 "customers/x/campaigns/1"},
            )
        assert res.ok
        op = captured["body"]["operations"][0]
        assert op["update"]["status"] == "ENABLED"


# ── performance ──────────────────────────────────────────


class TestPerformance:
    def test_requires_resource_and_dates(self, monkeypatch):
        a = _adapter(monkeypatch)
        res = a.execute(
            Capability.ADS_GET_PERFORMANCE,
            {"start_date": "2026-04-01"},
        )
        assert not res.ok

    def test_gaql_query_shape(self, monkeypatch):
        a = _adapter(monkeypatch)
        captured = {}

        def fake_request(method, path, *, body=None, params=None):
            captured["body"] = body
            captured["path"] = path
            return {
                "results": [{
                    "metrics": {
                        "impressions": "12000",
                        "clicks": "300",
                        "ctr": 0.025,
                        "cost_micros": "25500000",
                        "conversions": 7.0,
                    },
                }],
            }

        with patch.object(
            a, "_api_request", side_effect=fake_request,
        ):
            res = a.execute(
                Capability.ADS_GET_PERFORMANCE,
                {
                    "campaign_resource":
                        "customers/x/campaigns/1",
                    "start_date": "2026-04-01",
                    "end_date": "2026-04-24",
                },
            )
        assert res.ok
        assert "googleAds:search" in captured["path"]
        query = captured["body"]["query"]
        assert "campaign.resource_name" in query
        assert "'2026-04-01'" in query
        assert "'2026-04-24'" in query
        m = res.data["metrics"]
        assert m["impressions"] == 12000
        assert m["clicks"] == 300
        # cost_micros → USD conversion.
        assert m["cost_usd"] == 25.50
        assert m["conversions"] == 7


# ── OAuth refresh flow ───────────────────────────────────


class TestOAuthRefresh:
    def test_refresh_token_exchange(self, monkeypatch):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        _configure(monkeypatch)
        a = GoogleAdsAdapter()

        class _FakeResp:
            status_code = 200
            text = "{}"

            def json(self):
                return {
                    "access_token": "ya29-new",
                    "expires_in": 3599,
                }

        with patch(
            "core.adapters.ads.google_ads._requests.post",
            return_value=_FakeResp(),
        ):
            token, ttl = a._refresh_token()
        assert token == "ya29-new"
        assert ttl == 3599.0

    def test_refresh_token_cached_between_calls(
        self, monkeypatch,
    ):
        from core.adapters.ads.google_ads import GoogleAdsAdapter
        _configure(monkeypatch)
        a = GoogleAdsAdapter()
        call_count = {"n": 0}

        def fake_refresh():
            call_count["n"] += 1
            return ("tok", 600.0)

        with patch.object(
            a, "_refresh_token", side_effect=fake_refresh,
        ):
            assert a._access_token() == "tok"
            assert a._access_token() == "tok"
        assert call_count["n"] == 1


# ── Bootstrap ────────────────────────────────────────────


class TestBootstrap:
    def test_google_registered(self):
        from core.adapters.ads.bootstrap import register_all
        status = register_all()
        assert "google_ads" in status

    def test_configured_when_env_set(self, monkeypatch):
        from core.adapters.ads.bootstrap import register_all
        _configure(monkeypatch)
        status = register_all()
        assert status["google_ads"] is True

    def test_meta_still_highest_priority(self, monkeypatch):
        """Three adapters: Meta (80) > TikTok (75) >
        Google (70). Router picks Meta when all configured."""
        from core.adapters import get_router
        from core.adapters.ads.bootstrap import register_all
        _configure(monkeypatch)
        monkeypatch.setenv(
            "TIKTOK_ADS_ACCESS_TOKEN", "t" * 40,
        )
        monkeypatch.setenv(
            "TIKTOK_ADS_ADVERTISER_ID", "99",
        )
        monkeypatch.setenv(
            "META_ADS_ACCESS_TOKEN", "m" * 40,
        )
        monkeypatch.setenv(
            "META_ADS_ACCOUNT_ID", "act_1",
        )
        get_config().reload()
        register_all()
        chosen = get_router().route(
            Capability.ADS_CREATE_CAMPAIGN,
        )
        assert chosen.name == "meta_ads"
