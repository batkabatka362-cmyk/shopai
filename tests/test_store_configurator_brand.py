"""StoreConfigurator brand + SEO metafield tests (Phase 2a).

Writes structured brand + SEO-default metafields so every AI
engine (content generator, email templates, ad copy,
schema-org emitter) reads from one canonical source.
"""
from __future__ import annotations

import json

import pytest


def _make(dry_run: bool = False):
    from execution.store_configurator import StoreConfigurator
    return StoreConfigurator(dry_run=dry_run)


def _install_fake_client(
    monkeypatch, responses=None, track_calls=None,
):
    responses = responses or {}
    track_calls = (
        track_calls if track_calls is not None else []
    )

    class FakeClient:
        def __init__(self, shop_url, token, **kw):
            self.shop_url = shop_url

        def get(self, path, *, params=None):
            track_calls.append(("GET", path, params))
            return responses.get(f"GET {path}", {})

        def post(self, path, *, json=None):
            track_calls.append(("POST", path, json))
            return responses.get(
                f"POST {path}",
                {"metafield": {"id": 1}},
            )

        def put(self, path, *, json=None):
            track_calls.append(("PUT", path, json))
            return responses.get(f"PUT {path}", {})

        def delete(self, path):
            track_calls.append(("DELETE", path, None))
            return responses.get(f"DELETE {path}", {})

    monkeypatch.setattr(
        "execution.store_configurator.ShopifyClient",
        FakeClient,
    )
    return track_calls


class TestBrandFeatureEnabled:
    def test_brand_in_all_features(self):
        from execution.store_configurator import ALL_FEATURES
        assert "brand" in ALL_FEATURES


class TestBrandDryRun:
    def test_both_metafields_planned(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="tech", store_name="Gadget Hub",
            features=["brand"],
        )
        b = result["results"]["brand"]
        assert b["status"] == "dry_run"
        assert set(b["written"]) == {"brand", "seo_defaults"}
        assert b["errors"] == []


class TestBrandLive:
    def test_two_metafield_posts(self, monkeypatch):
        calls = _install_fake_client(monkeypatch)
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            niche="beauty", store_name="Glow Co",
            features=["brand"],
        )
        posts = [
            c for c in calls
            if c[0] == "POST"
            and c[1] == "metafields.json"
        ]
        assert len(posts) == 2
        # Verify namespace + keys
        keys = sorted(
            p[2]["metafield"]["key"] for p in posts
        )
        assert keys == ["brand", "seo_defaults"]
        for p in posts:
            assert p[2]["metafield"]["namespace"] == "shopai"
            assert p[2]["metafield"]["type"] == "json"
        b = result["results"]["brand"]
        assert b["status"] == "success"
        assert b["niche"] == "beauty"
        assert b["store_name"] == "Glow Co"

    def test_partial_failure_recorded(self, monkeypatch):
        # First POST succeeds, second errors.
        call_count = {"n": 0}

        class FakeClient:
            def __init__(self, *a, **kw): pass
            def get(self, path, *, params=None):
                return {}
            def post(self, path, *, json=None):
                call_count["n"] += 1
                if call_count["n"] == 2:
                    return {"error": "bad request"}
                return {"metafield": {"id": 1}}
            def put(self, path, *, json=None):
                return {}
            def delete(self, path):
                return {}

        monkeypatch.setattr(
            "execution.store_configurator.ShopifyClient",
            FakeClient,
        )
        c = _make(dry_run=False)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["brand"],
        )
        b = result["results"]["brand"]
        assert b["status"] == "partial"
        assert len(b["written"]) == 1
        assert len(b["errors"]) == 1


class TestBrandTemplates:
    def test_all_niches_produce_valid_metafields(self):
        from execution.store_configurator import (
            _brand_metafields,
        )
        for niche in (
            "home", "fashion", "tech", "beauty", "general",
        ):
            fields = _brand_metafields(niche, "TestCo")
            assert len(fields) == 2
            for mf in fields:
                assert mf["namespace"] == "shopai"
                assert mf["type"] == "json"
                # Value must be valid JSON
                parsed = json.loads(mf["value"])
                assert isinstance(parsed, dict)

    def test_brand_metafield_contains_expected_keys(self):
        from execution.store_configurator import (
            _brand_metafields,
        )
        fields = _brand_metafields("fashion", "Vogue")
        brand = next(
            f for f in fields if f["key"] == "brand"
        )
        v = json.loads(brand["value"])
        for k in (
            "store_name", "niche", "voice", "tagline",
            "color_primary", "color_secondary",
            "typography",
        ):
            assert k in v
        assert v["store_name"] == "Vogue"
        assert v["niche"] == "fashion"
        assert "confident" in v["voice"]

    def test_seo_defaults_contains_schema_type(self):
        from execution.store_configurator import (
            _brand_metafields,
        )
        fields = _brand_metafields("beauty", "GlowCo")
        seo = next(
            f for f in fields if f["key"] == "seo_defaults"
        )
        v = json.loads(seo["value"])
        assert "schema_org_type" in v
        assert v["schema_org_type"] == "BeautySalon"
        assert "meta_description_template" in v
        assert "GlowCo" in v["meta_description_template"]

    def test_unknown_niche_falls_back(self):
        from execution.store_configurator import (
            _brand_metafields,
        )
        fields = _brand_metafields("zzzz", "X")
        brand = next(
            f for f in fields if f["key"] == "brand"
        )
        v = json.loads(brand["value"])
        assert "friendly" in v["voice"]  # general voice

    def test_empty_store_name_falls_back(self):
        from execution.store_configurator import (
            _brand_metafields,
        )
        fields = _brand_metafields("general", "")
        brand = next(
            f for f in fields if f["key"] == "brand"
        )
        v = json.loads(brand["value"])
        assert v["store_name"] == "Our Store"
