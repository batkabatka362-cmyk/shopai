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
            "product_tags", "ai_config", "gifts", "loyalty", "referral",
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
        from execution.store_configurator import ALL_FEATURES
        assert len(result["features"]) == len(ALL_FEATURES)


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
    _CORE_CODES = {"WELCOME15", "COMEBACK10", "BUNDLE15", "FREESHIP50", "LOYAL20"}

    def _responses(self, existing=None):
        return {
            "GET price_rules.json": {"price_rules": existing or []},
            "POST price_rules.json": {"price_rule": {"id": 42}},
        }

    def test_creates_all_core_discounts(self, monkeypatch):
        _install_fake_client(monkeypatch, responses=self._responses())
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        codes = set(result["results"]["discounts"]["codes"])
        assert self._CORE_CODES.issubset(codes)
        # Plus the moderate-strategy SAVE10 and one seasonal code
        assert "SAVE10" in codes
        assert result["results"]["discounts"]["seasonal"] in codes

    def test_seasonal_code_matches_current_month(self, monkeypatch):
        import time as _t
        _install_fake_client(monkeypatch, responses=self._responses())
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        from execution.store_configurator import StoreConfigurator
        expected = StoreConfigurator._SEASONAL_CODES[_t.gmtime().tm_mon][0]
        assert result["results"]["discounts"]["seasonal"] == expected
        assert expected in result["results"]["discounts"]["codes"]

    def test_aggressive_strategy_adds_flash_and_bogo(self, monkeypatch):
        _install_fake_client(monkeypatch, responses=self._responses())
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="fashion",
            features=["discounts"],
        )
        codes = set(result["results"]["discounts"]["codes"])
        assert {"FLASH25", "BOGO50"}.issubset(codes)
        assert self._CORE_CODES.issubset(codes)

    def test_generous_strategy_adds_beauty(self, monkeypatch):
        _install_fake_client(monkeypatch, responses=self._responses())
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="beauty",
            features=["discounts"],
        )
        assert "BEAUTY20" in result["results"]["discounts"]["codes"]

    def test_existing_discount_not_recreated(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._responses(existing=[{"title": "WELCOME15"}]),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        assert "WELCOME15" not in result["results"]["discounts"]["codes"]
        # But other core codes still created
        codes = set(result["results"]["discounts"]["codes"])
        assert "COMEBACK10" in codes
        assert "BUNDLE15" in codes

    def test_bundle_has_min_quantity_rule(self, monkeypatch):
        calls = _install_fake_client(monkeypatch, responses=self._responses())
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        bundle_body = None
        for m, p, b in calls:
            if m == "POST" and p == "price_rules.json" and b:
                if b["price_rule"]["title"] == "BUNDLE15":
                    bundle_body = b
                    break
        assert bundle_body is not None
        assert bundle_body["price_rule"]["prerequisite_quantity_range"] == {
            "greater_than_or_equal_to": 3,
        }

    def test_free_shipping_uses_shipping_target_and_min_subtotal(self, monkeypatch):
        calls = _install_fake_client(monkeypatch, responses=self._responses())
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        ship_body = None
        for m, p, b in calls:
            if m == "POST" and p == "price_rules.json" and b:
                if b["price_rule"]["title"] == "FREESHIP50":
                    ship_body = b
                    break
        assert ship_body is not None
        assert ship_body["price_rule"]["target_type"] == "shipping_line"
        assert ship_body["price_rule"]["prerequisite_subtotal_range"] == {
            "greater_than_or_equal_to": "50.0",
        }
        assert ship_body["price_rule"]["value"] == "-100.0"

    def test_welcome_and_loyal_once_per_customer(self, monkeypatch):
        calls = _install_fake_client(monkeypatch, responses=self._responses())
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        opc_codes = set()
        for m, p, b in calls:
            if m == "POST" and p == "price_rules.json" and b:
                if b["price_rule"].get("once_per_customer"):
                    opc_codes.add(b["price_rule"]["title"])
        assert {"WELCOME15", "COMEBACK10", "LOYAL20"}.issubset(opc_codes)

    def test_discount_codes_attached_after_rule(self, monkeypatch):
        calls = _install_fake_client(monkeypatch, responses=self._responses())
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        code_attachments = [
            (p, b) for m, p, b in calls
            if m == "POST" and "discount_codes.json" in p
        ]
        # One attach per core code + seasonal + SAVE10
        attached_codes = {b["discount_code"]["code"] for _, b in code_attachments if b}
        assert self._CORE_CODES.issubset(attached_codes)


class TestSeasonalDiscountTable:
    def test_all_months_defined(self):
        from execution.store_configurator import StoreConfigurator
        assert set(StoreConfigurator._SEASONAL_CODES.keys()) == set(range(1, 13))
        for month, (code, value, _desc) in StoreConfigurator._SEASONAL_CODES.items():
            assert isinstance(code, str) and code
            assert -50 <= value < 0, f"month {month} value {value} out of range"


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


class TestGifts:
    _PRODUCTS = [
        {"id": 1, "title": "Cheap Candle", "tags": "home",
         "variants": [{"price": "8", "inventory_quantity": 25}]},
        {"id": 2, "title": "Mid Lamp", "tags": "home",
         "variants": [{"price": "40", "inventory_quantity": 10}]},
        {"id": 3, "title": "Premium Sofa", "tags": "home, premium",
         "variants": [{"price": "500", "inventory_quantity": 3}]},
        {"id": 4, "title": "Out of stock", "tags": "home",
         "variants": [{"price": "5", "inventory_quantity": 0}]},
    ]

    def test_picks_cheapest_eligible_product(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET products.json": {"products": self._PRODUCTS},
                "POST metafields.json": {"metafield": {"id": 1}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["gifts"],
        )
        g = result["results"]["gifts"]
        assert g["saved"] is True
        assert g["gift_product_id"] == 1  # cheapest in-stock, not premium
        assert g["threshold"] == 75.0  # home niche
        assert g["tagged"] is True

    def test_premium_product_excluded(self, monkeypatch):
        products = [
            {"id": 1, "title": "Premium", "tags": "premium",
             "variants": [{"price": "5", "inventory_quantity": 10}]},
            {"id": 2, "title": "Regular", "tags": "home",
             "variants": [{"price": "15", "inventory_quantity": 10}]},
        ]
        _install_fake_client(
            monkeypatch,
            responses={
                "GET products.json": {"products": products},
                "POST metafields.json": {"metafield": {"id": 1}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", features=["gifts"],
        )
        assert result["results"]["gifts"]["gift_product_id"] == 2

    def test_no_gift_tag_excluded(self, monkeypatch):
        products = [
            {"id": 1, "title": "Skip me", "tags": "no-gift",
             "variants": [{"price": "5", "inventory_quantity": 10}]},
            {"id": 2, "title": "Use me", "tags": "home",
             "variants": [{"price": "20", "inventory_quantity": 10}]},
        ]
        _install_fake_client(
            monkeypatch,
            responses={
                "GET products.json": {"products": products},
                "POST metafields.json": {"metafield": {"id": 1}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", features=["gifts"],
        )
        assert result["results"]["gifts"]["gift_product_id"] == 2

    def test_no_eligible_product_still_saves_program(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "GET products.json": {"products": []},
                "POST metafields.json": {"metafield": {"id": 1}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", features=["gifts"],
        )
        assert result["results"]["gifts"]["saved"] is True
        assert result["results"]["gifts"]["gift_product_id"] is None
        assert result["results"]["gifts"]["tagged"] is False

    def test_metafield_body_contains_program(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET products.json": {"products": self._PRODUCTS},
                "POST metafields.json": {"metafield": {"id": 1}},
            },
        )
        c = _make()
        c.configure("x.myshopify.com", "tok", niche="beauty",
                    features=["gifts"])
        mf_bodies = [b for m, p, b in calls if p == "metafields.json" and m == "POST"]
        gift_body = next(b for b in mf_bodies if b["metafield"]["key"] == "gifts")
        program = json.loads(gift_body["metafield"]["value"])
        assert program["enabled"] is True
        assert program["threshold_usd"] == 50.0
        assert "free gift" in program["message"].lower()


class TestLoyalty:
    def test_saves_program_metafield(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={"POST metafields.json": {"metafield": {"id": 1}}},
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="beauty",
            features=["loyalty"],
        )
        assert result["results"]["loyalty"]["saved"] is True
        # Beauty has the richest loyalty rules
        assert result["results"]["loyalty"]["earn_per_dollar"] == 2
        assert result["results"]["loyalty"]["welcome_bonus"] == 100
        assert result["results"]["loyalty"]["tiers"] == 4

    def test_metafield_body_has_tier_structure(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={"POST metafields.json": {"metafield": {"id": 1}}},
        )
        c = _make()
        c.configure("x.myshopify.com", "tok", niche="home",
                    features=["loyalty"])
        mf_bodies = [b for m, p, b in calls if p == "metafields.json" and m == "POST"]
        loyalty_body = next(b for b in mf_bodies if b["metafield"]["key"] == "loyalty")
        program = json.loads(loyalty_body["metafield"]["value"])
        tiers = program["tiers"]
        assert [t["name"] for t in tiers] == ["Bronze", "Silver", "Gold", "Platinum"]
        # Tiers should have monotonically increasing thresholds
        thresholds = [t["min_points"] for t in tiers]
        assert thresholds == sorted(thresholds)
        # Multipliers should also be monotonic
        assert [t["multiplier"] for t in tiers] == [1.0, 1.25, 1.5, 2.0]


class TestReferral:
    def test_creates_friend10_and_metafield(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET price_rules.json": {"price_rules": []},
                "POST price_rules.json": {"price_rule": {"id": 55}},
                "POST metafields.json": {"metafield": {"id": 1}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", features=["referral"],
        )
        r = result["results"]["referral"]
        assert r["saved"] is True
        assert r["discount_code"] == "FRIEND10"
        assert r["code_created"] is True
        # FRIEND10 price_rule was POSTed
        titles = [b["price_rule"]["title"] for m, p, b in calls
                  if m == "POST" and p == "price_rules.json" and b]
        assert "FRIEND10" in titles

    def test_skips_rule_creation_if_exists(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "GET price_rules.json": {"price_rules": [{"title": "FRIEND10"}]},
                "POST metafields.json": {"metafield": {"id": 1}},
            },
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", features=["referral"],
        )
        assert result["results"]["referral"]["code_created"] is False
        assert result["results"]["referral"]["saved"] is True  # metafield still saved

    def test_metafield_body_has_reward_config(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={
                "GET price_rules.json": {"price_rules": []},
                "POST price_rules.json": {"price_rule": {"id": 55}},
                "POST metafields.json": {"metafield": {"id": 1}},
            },
        )
        c = _make()
        c.configure("x.myshopify.com", "tok", features=["referral"])
        mf_bodies = [b for m, p, b in calls if p == "metafields.json" and m == "POST"]
        ref_body = next(b for b in mf_bodies if b["metafield"]["key"] == "referral")
        program = json.loads(ref_body["metafield"]["value"])
        assert program["enabled"] is True
        assert program["discount_code"] == "FRIEND10"
        assert program["referrer_reward"]["type"] == "points"
        assert program["referred_reward"]["percent"] == 10


class TestAllFeaturesIncludesNewOnes:
    def test_all_features_count(self):
        from execution.store_configurator import ALL_FEATURES
        assert "gifts" in ALL_FEATURES
        assert "loyalty" in ALL_FEATURES
        assert "referral" in ALL_FEATURES
        assert len(ALL_FEATURES) == 9


class TestSingleton:
    def test_get_store_configurator_returns_singleton(self):
        from execution import store_configurator as mod
        mod._instance = None
        a = mod.get_store_configurator()
        b = mod.get_store_configurator()
        assert a is b
