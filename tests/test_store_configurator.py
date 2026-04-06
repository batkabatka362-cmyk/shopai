"""Baseline tests for StoreConfigurator.

Focuses on the current feature set (collections, discounts, shipping,
content, tags, ai_config) with ShopifyClient mocked at the HTTP-helper
level so no real Shopify calls are made.
"""
import json

import pytest


def _make(dry_run: bool = False):
    from execution.store_configurator import StoreConfigurator
    return StoreConfigurator(dry_run=dry_run)


def _install_fake_client(monkeypatch, responses=None, track_calls=None):
    """Replace ShopifyClient with a controllable fake.

    ``responses`` maps "METHOD path" to a dict response. Unknown calls
    return ``{}``. ``track_calls`` (if provided) is populated with
    every (method, path, body) tuple.
    """
    responses = responses or {}
    track_calls = track_calls if track_calls is not None else []

    class FakeClient:
        def __init__(self, shop_url, token, **kw):
            self.shop_url = shop_url

        def get(self, path, *, params=None):
            key = f"GET {path}"
            track_calls.append(("GET", path, params))
            return responses.get(key, {})

        def post(self, path, *, json=None):
            track_calls.append(("POST", path, json))
            return responses.get(f"POST {path}", {})

        def put(self, path, *, json=None):
            track_calls.append(("PUT", path, json))
            return responses.get(f"PUT {path}", {})

        def delete(self, path):
            track_calls.append(("DELETE", path, None))
            return responses.get(f"DELETE {path}", {})

    monkeypatch.setattr("execution.store_configurator.ShopifyClient", FakeClient)
    return track_calls


class TestConfigureBasic:
    def test_unknown_niche_falls_back_to_general(self, monkeypatch):
        calls = _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure("x.myshopify.com", "tok", niche="zzzz")
        assert result["status"] == "planned"
        # "general" niche collections should appear in the plan
        plan = result["plan"]
        titles_planned = " ".join(
            e["body_preview"] for e in plan if "smart_collections.json" in e["path"]
        )
        assert "Best Sellers" in titles_planned or "New In" in titles_planned

    def test_all_features_selected_by_default(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure("x.myshopify.com", "tok", niche="home")
        assert set(result["features"]) == {
            "collections", "discounts", "shipping", "content",
            "product_tags", "ai_config",
        }

    def test_selective_features(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["collections", "discounts"],
        )
        assert set(result["features"]) == {"collections", "discounts"}
        assert "shipping" not in result["results"]
        assert "content" not in result["results"]

    def test_invalid_feature_ignored_with_warning(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok",
            features=["collections", "bogus"],
        )
        assert "collections" in result["features"]

    def test_empty_feature_list_still_runs_all(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure("x.myshopify.com", "tok", features=[])
        assert len(result["features"]) == 6


class TestCollections:
    def test_creates_missing_collections(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET smart_collections.json": {"smart_collections": []},
                "POST smart_collections.json": {"smart_collection": {"id": 1}},
            },
        )
        c = _make()
        result = c.configure("x.myshopify.com", "tok", niche="home",
                             features=["collections"])
        assert result["results"]["collections"]["created"] > 0
        post_paths = [p for m, p, _ in calls if m == "POST" and "smart_collections" in p]
        # 5 niche + 2 price-based + 0 smart (no products) = 7
        assert len(post_paths) == 7

    def test_skips_existing_collections(self, monkeypatch):
        existing = [{"title": "Home Decor"}, {"title": "Lighting"}]
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET smart_collections.json": {"smart_collections": existing},
                "POST smart_collections.json": {"smart_collection": {"id": 1}},
            },
        )
        c = _make()
        c.configure("x.myshopify.com", "tok", niche="home",
                    features=["collections"])
        post_count = sum(1 for m, p, _ in calls
                         if m == "POST" and "smart_collections" in p)
        # 7 total - 2 existing = 5 created
        assert post_count == 5


class TestSmartCollections:
    """Data-driven collections derived from actual product data."""

    def _products_response(self, products):
        return {
            "GET smart_collections.json": {"smart_collections": []},
            "GET products.json": {"products": products},
            "POST smart_collections.json": {"smart_collection": {"id": 1}},
        }

    def test_bestsellers_created_when_tag_present(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses=self._products_response([
                {"id": 1, "title": "Widget", "tags": "bestseller, home",
                 "variants": [{"price": "25"}]},
            ]),
        )
        c = _make()
        result = c.configure("x.myshopify.com", "tok", niche="home",
                             features=["collections"])
        descriptions = [b["smart_collection"]["title"]
                        for m, p, b in calls
                        if m == "POST" and "smart_collections" in p and b]
        assert "Bestsellers" in descriptions
        assert result["results"]["collections"]["analysis"]["has_bestsellers"] is True

    def test_bestsellers_skipped_when_no_tag(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses=self._products_response([
                {"id": 1, "title": "Plain", "tags": "home",
                 "variants": [{"price": "25"}]},
            ]),
        )
        c = _make()
        result = c.configure("x.myshopify.com", "tok", niche="home",
                             features=["collections"])
        titles = [b["smart_collection"]["title"]
                  for m, p, b in calls
                  if m == "POST" and "smart_collections" in p and b]
        assert "Bestsellers" not in titles
        assert result["results"]["collections"]["skipped_empty"] >= 1

    def test_new_arrivals_based_on_created_at(self, monkeypatch):
        import time as _t
        recent = _t.strftime("%Y-%m-%dT00:00:00+00:00",
                              _t.gmtime(_t.time() - 5 * 86400))  # 5 days ago
        old = "2020-01-01T00:00:00+00:00"
        calls = _install_fake_client(
            monkeypatch,
            responses=self._products_response([
                {"id": 1, "title": "New", "tags": "home",
                 "created_at": recent, "variants": [{"price": "25"}]},
                {"id": 2, "title": "Old", "tags": "home",
                 "created_at": old, "variants": [{"price": "25"}]},
            ]),
        )
        c = _make()
        result = c.configure("x.myshopify.com", "tok", niche="home",
                             features=["collections"])
        assert result["results"]["collections"]["analysis"]["has_new_arrivals"] is True
        assert result["results"]["collections"]["analysis"]["new_count"] == 1
        titles = [b["smart_collection"]["title"]
                  for m, p, b in calls
                  if m == "POST" and b]
        assert "New Arrivals" in titles

    def test_low_stock_flagged_when_inventory_low(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses=self._products_response([
                {"id": 1, "title": "Running out", "tags": "home",
                 "variants": [{"price": "25", "inventory_quantity": 3}]},
                {"id": 2, "title": "Plenty", "tags": "home",
                 "variants": [{"price": "25", "inventory_quantity": 50}]},
            ]),
        )
        c = _make()
        result = c.configure("x.myshopify.com", "tok", niche="home",
                             features=["collections"])
        assert result["results"]["collections"]["analysis"]["has_low_stock"] is True
        assert result["results"]["collections"]["analysis"]["low_stock_count"] == 1

    def test_gift_ideas_from_title_or_tag(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses=self._products_response([
                {"id": 1, "title": "Gift Basket", "tags": "home",
                 "variants": [{"price": "25"}]},
            ]),
        )
        c = _make()
        result = c.configure("x.myshopify.com", "tok", niche="home",
                             features=["collections"])
        assert result["results"]["collections"]["analysis"]["has_gift_ideas"] is True

    def test_empty_product_list_creates_no_smart_collections(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses=self._products_response([]),
        )
        c = _make()
        result = c.configure("x.myshopify.com", "tok", niche="home",
                             features=["collections"])
        # 7 baseline (5 niche + 2 price), 0 smart
        assert result["results"]["collections"]["created"] == 7
        assert result["results"]["collections"]["skipped_empty"] == 6

    def test_top_rated_and_back_in_stock_flags(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._products_response([
                {"id": 1, "title": "Great", "tags": "top-rated",
                 "variants": [{"price": "25"}]},
                {"id": 2, "title": "Restocked", "tags": "back-in-stock",
                 "variants": [{"price": "25"}]},
            ]),
        )
        c = _make()
        result = c.configure("x.myshopify.com", "tok", niche="home",
                             features=["collections"])
        a = result["results"]["collections"]["analysis"]
        assert a["has_top_rated"] is True
        assert a["has_back_in_stock"] is True

    def test_malformed_created_at_does_not_crash(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._products_response([
                {"id": 1, "title": "Bad date", "tags": "home",
                 "created_at": "not-a-date",
                 "variants": [{"price": "25"}]},
            ]),
        )
        c = _make()
        result = c.configure("x.myshopify.com", "tok", niche="home",
                             features=["collections"])
        assert result["results"]["collections"]["analysis"]["new_count"] == 0


class TestDiscounts:
    def test_creates_welcome_and_moderate(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET price_rules.json": {"price_rules": []},
                "POST price_rules.json": {"price_rule": {"id": 42}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        assert "WELCOME15" in result["results"]["discounts"]["codes"]
        assert "SAVE10" in result["results"]["discounts"]["codes"]

    def test_aggressive_strategy_adds_flash_and_bogo(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "GET price_rules.json": {"price_rules": []},
                "POST price_rules.json": {"price_rule": {"id": 42}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="fashion",
            features=["discounts"],
        )
        codes = set(result["results"]["discounts"]["codes"])
        assert {"WELCOME15", "FLASH25", "BOGO50"}.issubset(codes)

    def test_generous_strategy_adds_beauty(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "GET price_rules.json": {"price_rules": []},
                "POST price_rules.json": {"price_rule": {"id": 42}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="beauty",
            features=["discounts"],
        )
        assert "BEAUTY20" in result["results"]["discounts"]["codes"]

    def test_existing_discount_not_recreated(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "GET price_rules.json": {
                    "price_rules": [{"title": "WELCOME15"}],
                },
                "POST price_rules.json": {"price_rule": {"id": 42}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        assert "WELCOME15" not in result["results"]["discounts"]["codes"]


class TestShipping:
    def test_reads_zones(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "GET shipping_zones.json": {
                    "shipping_zones": [
                        {"name": "Domestic", "countries": [{"code": "US"}]},
                        {"name": "International", "countries": [
                            {"code": "CA"}, {"code": "GB"}]},
                    ],
                },
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", features=["shipping"],
        )
        assert result["results"]["shipping"]["zones"] == 2
        assert result["results"]["shipping"]["details"][1]["countries"] == 2


class TestContent:
    def test_creates_buying_guide(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET pages.json": {"pages": []},
                "POST pages.json": {"page": {"id": 99}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="beauty",
            features=["content"],
        )
        assert result["results"]["content"]["pages_created"] == 1
        page_post = next((b for m, p, b in calls if m == "POST" and p == "pages.json"), None)
        assert page_post is not None
        assert "Beauty" in page_post["page"]["title"]

    def test_skips_existing_guide(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "GET pages.json": {
                    "pages": [{"title": "Buying Guide: Best Home Products"}],
                },
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["content"],
        )
        assert result["results"]["content"]["pages_created"] == 0


class TestProductTags:
    def test_adds_niche_and_price_tags(self, monkeypatch):
        products = [
            {"id": 1, "tags": "", "variants": [{"price": "15"}]},    # budget
            {"id": 2, "tags": "existing", "variants": [{"price": "50"}]},  # premium
            {"id": 3, "tags": "", "variants": [{"price": "30"}]},    # gift
        ]
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET products.json": {"products": products},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["product_tags"],
        )
        assert result["results"]["product_tags"]["tagged"] == 3
        puts = [(p, b) for m, p, b in calls if m == "PUT" and "products" in p]
        # product 1 → budget-friendly + home
        body_1 = next(b for p, b in puts if "/1.json" in p)
        assert "budget-friendly" in body_1["product"]["tags"]
        assert "home" in body_1["product"]["tags"]
        # product 2 → premium + home + existing
        body_2 = next(b for p, b in puts if "/2.json" in p)
        assert "premium" in body_2["product"]["tags"]
        assert "existing" in body_2["product"]["tags"]
        # product 3 → gift-idea + home
        body_3 = next(b for p, b in puts if "/3.json" in p)
        assert "gift-idea" in body_3["product"]["tags"]

    def test_no_change_when_tags_already_correct(self, monkeypatch):
        products = [
            {"id": 1, "tags": "budget-friendly, home", "variants": [{"price": "15"}]},
        ]
        calls = _install_fake_client(
            monkeypatch,
            responses={"GET products.json": {"products": products}},
        )
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["product_tags"],
        )
        puts = [m for m, p, b in calls if m == "PUT"]
        assert len(puts) == 0


class TestAiConfig:
    def test_writes_metafield(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "POST metafields.json": {"metafield": {"id": 7}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="tech",
            features=["ai_config"],
        )
        assert result["results"]["ai_config"]["saved"] is True
        mf_post = next(b for m, p, b in calls if p == "metafields.json")
        value = json.loads(mf_post["metafield"]["value"])
        assert value["niche"] == "tech"
        assert "configured_at" in value


class TestDryRun:
    def test_plan_contains_intended_writes(self, monkeypatch):
        _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["collections"],
        )
        assert result["status"] == "planned"
        assert result["plan"] is not None
        # Should describe creating each collection
        descriptions = [p["description"] for p in result["plan"]]
        assert any("Create smart collection 'Home Decor'" in d for d in descriptions)

    def test_dry_run_does_not_call_post(self, monkeypatch):
        calls = _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["collections", "discounts"],
        )
        post_calls = [m for m, p, b in calls if m == "POST"]
        assert len(post_calls) == 0

    def test_dry_run_still_reads(self, monkeypatch):
        calls = _install_fake_client(monkeypatch)
        c = _make(dry_run=True)
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["collections"],
        )
        get_calls = [p for m, p, b in calls if m == "GET"]
        assert "smart_collections.json" in get_calls

    def test_dry_run_does_not_record_action(self, monkeypatch):
        _install_fake_client(monkeypatch)
        with pytest.MonkeyPatch.context() as mp:
            called = {"n": 0}
            # Stub get_data_architecture so we can tell if it was invoked
            import core.data.architecture as arch

            class FakeDA:
                def capture(self, *a, **kw):
                    called["n"] += 1

            mp.setattr(arch, "get_data_architecture", lambda: FakeDA())
            c = _make(dry_run=True)
            c.configure("x.myshopify.com", "tok", features=["ai_config"])
        assert called["n"] == 0


class TestSingleton:
    def test_get_store_configurator_returns_singleton(self):
        from execution import store_configurator as mod
        mod._instance = None
        a = mod.get_store_configurator()
        b = mod.get_store_configurator()
        assert a is b
