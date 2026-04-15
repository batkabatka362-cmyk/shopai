"""Tests for ads intelligence (spy) adapters.

Real HTTP calls are forbidden — every test patches
``_http_request`` to return canned responses. The tests verify:

  * Metadata (category, capabilities, priority)
  * Configuration detection (env var → is_configured)
  * Request shape (correct URL, headers, params, body)
  * Response normalisation (vendor shape → unified record)
  * Capability dispatch (unsupported → AdapterValidationError)
  * Validation (missing query, out-of-range limits, malformed IDs)
  * Bootstrap registration (every adapter registers and is
    discoverable by capability)
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
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "MINEA_API_KEY", "PIPIADS_API_KEY", "BIGSPY_API_KEY",
        "FB_ADS_LIBRARY_TOKEN",
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


def _cfg(monkeypatch, **kv):
    for k, v in kv.items():
        monkeypatch.setenv(k, v)
    get_config().reload()


# ── Minea ────────────────────────────────────────────────────


class TestMineaMetadata:
    def test_metadata(self):
        from core.adapters.ads_spy.minea import MineaAdapter
        a = MineaAdapter()
        assert a.name == "minea"
        assert a.category == AdapterCategory.SCRAPER
        assert Capability.ADS_SPY_SEARCH in a.capabilities
        assert Capability.ADS_SPY_TOP_PRODUCTS in a.capabilities
        assert Capability.ADS_SPY_AD_DETAILS in a.capabilities
        assert a.priority == 90

    def test_unconfigured_without_key(self):
        from core.adapters.ads_spy.minea import MineaAdapter
        assert not MineaAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.ads_spy.minea import MineaAdapter
        _cfg(monkeypatch, MINEA_API_KEY="mk-test")
        assert MineaAdapter().is_configured()


class TestMineaSearch:
    def test_search_happy_path(self, monkeypatch):
        from core.adapters.ads_spy.minea import MineaAdapter
        _cfg(monkeypatch, MINEA_API_KEY="mk-test")
        a = MineaAdapter()

        raw = {
            "ads": [
                {
                    "ad_id": "m-1",
                    "advertiser": "CoolGadget.co",
                    "product_url": "https://coolgadget.co/p/1",
                    "first_seen": "2026-01-01",
                    "last_seen": "2026-04-10",
                    "engagement": {
                        "likes": 1200, "comments": 30,
                        "shares": 50, "views": 45000,
                    },
                    "country_targets": ["US", "CA"],
                    "language": "en",
                    "product_signals": {
                        "price_estimate": 29.99,
                        "store_platform": "shopify",
                        "category_hint": "home_gadget",
                    },
                    "raw_url": "https://minea.com/ad/m-1",
                },
            ],
        }
        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.ADS_SPY_SEARCH,
                {"query": "led slippers", "limit": 10, "country": "US"},
            )

        assert result.ok
        assert result.data["source"] == "minea"
        assert result.data["total"] == 1
        rec = result.data["ads"][0]
        assert rec["ad_id"] == "m-1"
        assert rec["advertiser"] == "CoolGadget.co"
        # days_running auto-computed from first/last_seen
        assert rec["days_running"] == 99
        assert rec["engagement"]["likes"] == 1200
        assert rec["country_targets"] == ["US", "CA"]
        assert rec["product_signals"]["price_estimate"] == 29.99

    def test_search_missing_query(self, monkeypatch):
        from core.adapters.ads_spy.minea import MineaAdapter
        _cfg(monkeypatch, MINEA_API_KEY="mk-test")
        a = MineaAdapter()
        result = a.execute(Capability.ADS_SPY_SEARCH, {"limit": 5})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_search_limit_out_of_range(self, monkeypatch):
        from core.adapters.ads_spy.minea import MineaAdapter
        _cfg(monkeypatch, MINEA_API_KEY="mk-test")
        a = MineaAdapter()
        result = a.execute(
            Capability.ADS_SPY_SEARCH,
            {"query": "x", "limit": 10_000},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


class TestMineaTopProducts:
    def test_top_products_happy_path(self, monkeypatch):
        from core.adapters.ads_spy.minea import MineaAdapter
        _cfg(monkeypatch, MINEA_API_KEY="mk-test")
        a = MineaAdapter()

        raw = {
            "results": [
                {"ad_id": "m-2", "advertiser": "PetCo",
                 "first_seen": "2026-03-01", "last_seen": "2026-04-10"},
                {"ad_id": "m-3", "advertiser": "Gadgetry"},
            ],
        }
        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.ADS_SPY_TOP_PRODUCTS,
                {"limit": 50, "country": "US", "category": "pet"},
            )

        assert result.ok
        assert result.data["total"] == 2
        assert result.data["ads"][0]["days_running"] == 40


class TestMineaAdDetails:
    def test_ad_details_happy_path(self, monkeypatch):
        from core.adapters.ads_spy.minea import MineaAdapter
        _cfg(monkeypatch, MINEA_API_KEY="mk-test")
        a = MineaAdapter()
        raw = {"ad": {"ad_id": "m-9", "advertiser": "X"}}
        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.ADS_SPY_AD_DETAILS, {"ad_id": "m-9"},
            )
        assert result.ok
        assert result.data["total"] == 1
        assert result.data["ads"][0]["advertiser"] == "X"

    def test_ad_details_requires_id(self, monkeypatch):
        from core.adapters.ads_spy.minea import MineaAdapter
        _cfg(monkeypatch, MINEA_API_KEY="mk-test")
        a = MineaAdapter()
        result = a.execute(Capability.ADS_SPY_AD_DETAILS, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── PiPiAds ──────────────────────────────────────────────────


class TestPiPiAdsMetadata:
    def test_metadata(self):
        from core.adapters.ads_spy.pipiads import PiPiAdsAdapter
        a = PiPiAdsAdapter()
        assert a.name == "pipiads"
        assert a.priority == 85
        assert Capability.ADS_SPY_SEARCH in a.capabilities

    def test_unconfigured_without_key(self):
        from core.adapters.ads_spy.pipiads import PiPiAdsAdapter
        assert not PiPiAdsAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.ads_spy.pipiads import PiPiAdsAdapter
        _cfg(monkeypatch, PIPIADS_API_KEY="pp-test")
        assert PiPiAdsAdapter().is_configured()


class TestPiPiAdsSearch:
    def test_search_custom_envelope(self, monkeypatch):
        from core.adapters.ads_spy.pipiads import PiPiAdsAdapter
        _cfg(monkeypatch, PIPIADS_API_KEY="pp-test")
        a = PiPiAdsAdapter()

        raw = {
            "code": 0,
            "data": {
                "list": [
                    {"ad_id": "p-1", "advertiser": "TikShop"},
                ],
            },
        }
        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.ADS_SPY_SEARCH,
                {"query": "kitchen gadget"},
            )

        assert result.ok
        assert result.data["ads"][0]["ad_id"] == "p-1"

    def test_auth_header_uses_x_api_key(self, monkeypatch):
        from core.adapters.ads_spy.pipiads import PiPiAdsAdapter
        _cfg(monkeypatch, PIPIADS_API_KEY="pp-test")
        a = PiPiAdsAdapter()
        headers = a._auth_headers()
        assert headers["X-API-Key"] == "pp-test"
        assert "Authorization" not in headers


# ── BigSpy ───────────────────────────────────────────────────


class TestBigSpyMetadata:
    def test_metadata(self):
        from core.adapters.ads_spy.bigspy import BigSpyAdapter
        a = BigSpyAdapter()
        assert a.name == "bigspy"
        assert a.priority == 75

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.ads_spy.bigspy import BigSpyAdapter
        _cfg(monkeypatch, BIGSPY_API_KEY="bs-test")
        assert BigSpyAdapter().is_configured()


class TestBigSpySearch:
    def test_search_nested_envelope(self, monkeypatch):
        from core.adapters.ads_spy.bigspy import BigSpyAdapter
        _cfg(monkeypatch, BIGSPY_API_KEY="bs-test")
        a = BigSpyAdapter()

        raw = {"data": {"list": [{"ad_id": "b-1", "advertiser": "BSco"}]}}
        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.ADS_SPY_SEARCH,
                {"query": "beauty", "limit": 5},
            )
        assert result.ok
        assert result.data["ads"][0]["ad_id"] == "b-1"


# ── Facebook Ads Library ─────────────────────────────────────


class TestFacebookAdsLibraryMetadata:
    def test_metadata(self):
        from core.adapters.ads_spy.facebook_ads_library import (
            FacebookAdsLibraryAdapter,
        )
        a = FacebookAdsLibraryAdapter()
        assert a.name == "fb_ads_library"
        assert a.priority == 60
        assert a.cost_per_call == 0.0

    def test_configured_without_key(self):
        """Public endpoint works without a token — is_configured
        must return True even when FB_ADS_LIBRARY_TOKEN is unset."""
        from core.adapters.ads_spy.facebook_ads_library import (
            FacebookAdsLibraryAdapter,
        )
        assert FacebookAdsLibraryAdapter().is_configured()


class TestFacebookAdsLibraryMapping:
    def test_map_graph_record_computes_days(self):
        from core.adapters.ads_spy.facebook_ads_library import (
            _map_graph_record,
        )
        row = {
            "id": "12345",
            "page_name": "Cool Brand",
            "ad_creative_link_titles": ["Headline here"],
            "ad_creative_bodies": ["Body copy"],
            "ad_creative_link_captions": ["coolbrand.com"],
            "ad_delivery_start_time": "2026-02-01T00:00:00+0000",
            "ad_delivery_stop_time": "2026-04-01T00:00:00+0000",
            "ad_snapshot_url": "https://fb.com/ads/archive/...",
            "impressions": {"lower_bound": 10000, "upper_bound": 20000},
        }
        rec = _map_graph_record(row)
        # Normaliser doesn't run here — just mapping
        assert rec["ad_id"] == "12345"
        assert rec["advertiser"] == "Cool Brand"
        assert rec["headline"] == "Headline here"
        assert rec["first_seen"] == "2026-02-01"
        assert rec["last_seen"] == "2026-04-01"
        assert rec["engagement"]["views"] == 10000

    def test_map_graph_record_open_ended_ad_uses_today(self):
        """Ads still running have no stop time — the mapper
        should fill with today's date so days_running reflects
        live duration rather than 0."""
        from datetime import date
        from core.adapters.ads_spy.facebook_ads_library import (
            _map_graph_record,
        )
        row = {
            "id": "67890",
            "page_name": "Live Brand",
            "ad_delivery_start_time": "2026-04-01T00:00:00+0000",
            # no ad_delivery_stop_time
        }
        rec = _map_graph_record(row)
        assert rec["first_seen"] == "2026-04-01"
        assert rec["last_seen"] == date.today().isoformat()


class TestFacebookAdsLibrarySearch:
    def test_search_happy_path(self, monkeypatch):
        from core.adapters.ads_spy.facebook_ads_library import (
            FacebookAdsLibraryAdapter,
        )
        a = FacebookAdsLibraryAdapter()

        raw = {
            "data": [
                {
                    "id": "1",
                    "page_name": "Brand",
                    "ad_creative_link_titles": ["Title"],
                    "ad_delivery_start_time": "2026-01-01T00:00:00+0000",
                    "ad_delivery_stop_time": "2026-04-01T00:00:00+0000",
                    "ad_snapshot_url": "https://fb.com/ads/1",
                },
            ],
        }
        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.ADS_SPY_SEARCH,
                {"query": "home gadget", "limit": 10, "country": "US"},
            )

        assert result.ok
        assert result.data["source"] == "fb_ads_library"
        rec = result.data["ads"][0]
        assert rec["ad_id"] == "1"
        assert rec["headline"] == "Title"
        assert rec["days_running"] == 90


class TestFacebookAdsLibraryTopProducts:
    def test_top_products_sorts_by_days_running(self, monkeypatch):
        from core.adapters.ads_spy.facebook_ads_library import (
            FacebookAdsLibraryAdapter,
        )
        a = FacebookAdsLibraryAdapter()

        raw = {
            "data": [
                {"id": "a", "page_name": "A",
                 "ad_delivery_start_time": "2026-04-01T00:00:00+0000",
                 "ad_delivery_stop_time":  "2026-04-10T00:00:00+0000"},
                {"id": "b", "page_name": "B",
                 "ad_delivery_start_time": "2026-01-01T00:00:00+0000",
                 "ad_delivery_stop_time":  "2026-04-10T00:00:00+0000"},
            ],
        }
        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.ADS_SPY_TOP_PRODUCTS,
                {"limit": 10, "category": "gadget"},
            )
        assert result.ok
        # Longest-running ad first
        assert result.data["ads"][0]["ad_id"] == "b"
        assert result.data["ads"][1]["ad_id"] == "a"


class TestFacebookAdsLibraryAdDetails:
    def test_ad_details_rejects_non_numeric_id(self):
        from core.adapters.ads_spy.facebook_ads_library import (
            FacebookAdsLibraryAdapter,
        )
        a = FacebookAdsLibraryAdapter()
        result = a.execute(
            Capability.ADS_SPY_AD_DETAILS, {"ad_id": "not-a-number"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Bootstrap / registry ─────────────────────────────────────


class TestBootstrap:
    def test_register_all_registers_four_adapters(self, monkeypatch):
        from core.adapters.ads_spy.bootstrap import register_all
        reset_registry()
        status = register_all()
        assert set(status.keys()) == {
            "minea", "pipiads", "bigspy", "fb_ads_library",
        }
        # FB Ads Library is configured-by-default (public endpoint);
        # the paid ones are unconfigured without env vars.
        assert status["fb_ads_library"] is True
        assert status["minea"] is False
        assert status["pipiads"] is False
        assert status["bigspy"] is False

    def test_router_finds_configured_spy_source(self, monkeypatch):
        from core.adapters.ads_spy.bootstrap import register_all
        _cfg(monkeypatch, MINEA_API_KEY="mk-test")
        reset_registry()
        register_all()

        reg = get_registry()
        candidates = reg.find_by_capability(
            Capability.ADS_SPY_SEARCH, configured_only=True,
        )
        names = [c.name for c in candidates]
        # Minea is highest-priority; FB Ads Library is free so
        # it's also configured. Both must be in the result.
        assert "minea" in names
        assert "fb_ads_library" in names
        # Minea (priority=90) ranks above fb_ads_library (60)
        assert names.index("minea") < names.index("fb_ads_library")


# ── Normalisation (base helper, vendor-agnostic) ─────────────


class TestNormalisation:
    def test_normalise_record_fills_missing_fields(self):
        from core.adapters.ads_spy._base import AdsSpyBaseAdapter

        class _Dummy(AdsSpyBaseAdapter):
            name = "dummy"
            base_url = "https://dummy"
            config_alias = ""
            requires_key = False

            def _do_search(self, c, p):  # pragma: no cover - not called
                raise NotImplementedError

            def _do_top_products(self, c, p):  # pragma: no cover
                raise NotImplementedError

            def _do_ad_details(self, c, p):  # pragma: no cover
                raise NotImplementedError

        a = _Dummy()
        rec = a._normalise_record({"ad_id": "z"})
        assert rec["ad_id"] == "z"
        assert rec["source"] == "dummy"
        assert rec["engagement"] == {
            "likes": 0, "comments": 0, "shares": 0, "views": 0,
        }
        assert rec["country_targets"] == []
        assert rec["product_signals"]["price_estimate"] == 0.0
        assert rec["days_running"] == 0

    def test_normalise_record_malformed_dates_safe(self):
        from core.adapters.ads_spy._base import AdsSpyBaseAdapter

        class _Dummy(AdsSpyBaseAdapter):
            name = "dummy"
            base_url = "https://dummy"
            config_alias = ""
            requires_key = False

            def _do_search(self, c, p):  # pragma: no cover
                raise NotImplementedError

            def _do_top_products(self, c, p):  # pragma: no cover
                raise NotImplementedError

            def _do_ad_details(self, c, p):  # pragma: no cover
                raise NotImplementedError

        a = _Dummy()
        rec = a._normalise_record({
            "first_seen": "not-a-date",
            "last_seen": "also-invalid",
        })
        # Should not raise; days_running just stays 0.
        assert rec["days_running"] == 0
