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
        from execution.store_configurator import ALL_FEATURES
        assert set(result["features"]) == set(ALL_FEATURES)

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

    # W963-162: tests rewritten around the router boundary.
    # Production code goes through SHOPIFY_LIST_DISCOUNTS
    # (read) + SHOPIFY_CREATE_DISCOUNT (write) via the
    # SmartRouter. The legacy REST-shape mocks were pinned
    # to a dead code path -- this rewrite pins each test to
    # the actual production contract.

    def _patch_router(
        self, monkeypatch, existing_titles=None,
    ):
        """Patch the router used by store_configurator's
        _existing_discount_titles helper + _create_discount.

        Returns a list of (capability_name, params) tuples
        for every router.execute call -- mirrors how the
        legacy REST tests collected calls via _install_fake_client.
        """
        calls: list[tuple[str, dict]] = []

        class FakeResult:
            def __init__(self, ok=True, data=None, error=""):
                self.ok = ok
                self.data = data or {}
                self.error = error

        class FakeRouter:
            def execute(self_inner, capability, params):
                cap_name = (
                    capability.value
                    if hasattr(capability, "value")
                    else str(capability)
                )
                calls.append((cap_name, dict(params)))
                if cap_name == "shopify_list_discounts":
                    return FakeResult(
                        ok=True,
                        data={
                            "discounts": [
                                {"title": t}
                                for t in (existing_titles or [])
                            ],
                        },
                    )
                if cap_name == "shopify_create_discount":
                    return FakeResult(
                        ok=True,
                        data={"discount_id": "gid://x/1"},
                    )
                if cap_name == (
                    "shopify_create_discount_free_shipping"
                ):
                    return FakeResult(
                        ok=True,
                        data={"id": "gid://x/2"},
                    )
                return FakeResult(ok=False, error="unknown")

        fake_router = FakeRouter()
        monkeypatch.setattr(
            "core.adapters.get_router",
            lambda: fake_router,
        )
        monkeypatch.setattr(
            "core.adapters.router.get_router",
            lambda: fake_router,
        )
        return calls

    def test_existing_discount_not_recreated(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._responses(),
        )
        self._patch_router(
            monkeypatch, existing_titles=["WELCOME15"],
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
        _install_fake_client(monkeypatch, responses=self._responses())
        calls = self._patch_router(monkeypatch)
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        bundle_params = None
        for cap, params in calls:
            if cap != "shopify_create_discount":
                continue
            if params.get("code") == "BUNDLE15":
                bundle_params = params
                break
        assert bundle_params is not None
        assert bundle_params.get("min_quantity") == 3

    def test_free_shipping_routes_to_free_shipping_mutation(self, monkeypatch):
        # W963-163: FREESHIP50 now routes through
        # SHOPIFY_CREATE_DISCOUNT_FREE_SHIPPING (Shopify's
        # dedicated free-shipping mutation), NOT the basic
        # percentage discount mutation. The latent gap from
        # W963-162's note is closed.
        _install_fake_client(monkeypatch, responses=self._responses())
        calls = self._patch_router(monkeypatch)
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        ship_params = None
        for cap, params in calls:
            if cap != "shopify_create_discount_free_shipping":
                continue
            if params.get("code") == "FREESHIP50":
                ship_params = params
                break
        assert ship_params is not None, (
            "FREESHIP50 must route through the free-shipping "
            "capability, not the basic discount mutation"
        )
        # Free-shipping doesn't carry a percentage; it carries
        # minimum_subtotal for the order-value gate.
        assert ship_params.get("minimum_subtotal") == 50.0
        assert "percentage" not in ship_params
        # And NO basic-discount call was made for FREESHIP50
        basic_for_freeship = [
            p for c2, p in calls
            if c2 == "shopify_create_discount"
            and p.get("code") == "FREESHIP50"
        ]
        assert not basic_for_freeship

    def test_welcome_and_loyal_once_per_customer(self, monkeypatch):
        _install_fake_client(monkeypatch, responses=self._responses())
        calls = self._patch_router(monkeypatch)
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        opc_codes = set()
        for cap, params in calls:
            if cap != "shopify_create_discount":
                continue
            if params.get("applies_once_per_customer"):
                opc_codes.add(params.get("code"))
        assert {"WELCOME15", "COMEBACK10", "LOYAL20"}.issubset(opc_codes)

    def test_core_codes_all_created_through_router(self, monkeypatch):
        # W963-162: every CORE code reaches the router. W963-163:
        # FREESHIP50 specifically routes through the free-shipping
        # capability while the others use the basic capability.
        _install_fake_client(monkeypatch, responses=self._responses())
        calls = self._patch_router(monkeypatch)
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["discounts"],
        )
        created_codes = {
            params.get("code")
            for cap, params in calls
            if cap in (
                "shopify_create_discount",
                "shopify_create_discount_free_shipping",
            )
        }
        assert self._CORE_CODES.issubset(created_codes)


class TestSeasonalDiscountTable:
    def test_all_months_defined(self):
        from execution.store_configurator import StoreConfigurator
        assert set(StoreConfigurator._SEASONAL_CODES.keys()) == set(range(1, 13))
        for month, (code, value, _desc) in StoreConfigurator._SEASONAL_CODES.items():
            assert isinstance(code, str) and code
            assert -50 <= value < 0, f"month {month} value {value} out of range"


class TestShipping:
    def _responses(self, zones):
        return {
            "GET shipping_zones.json": {"shipping_zones": zones},
            "POST metafields.json": {"metafield": {"id": 1}},
        }

    def test_reads_current_zones(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._responses([
                {"name": "Domestic", "countries": [{"code": "US"}]},
                {"name": "International", "countries": [
                    {"code": "CA"}, {"code": "GB"}]},
            ]),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home", features=["shipping"],
        )
        s = result["results"]["shipping"]
        assert s["current_zones"] == 2
        assert s["current_details"][1]["countries"] == 2

    def test_gap_analysis_detects_missing_countries(self, monkeypatch):
        # Home niche recommends US + CA + MX. We supply only US.
        _install_fake_client(
            monkeypatch,
            responses=self._responses([
                {"name": "Domestic", "countries": [{"code": "US"}]},
            ]),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home", features=["shipping"],
        )
        s = result["results"]["shipping"]
        assert s["fully_covered"] is False
        assert "CA" in s["gap_countries"]
        assert "MX" in s["gap_countries"]
        assert "US" not in s["gap_countries"]

    def test_fully_covered_when_all_recommended_present(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._responses([
                {"name": "Domestic", "countries": [{"code": "US"}]},
                {"name": "NorthAm", "countries": [
                    {"code": "CA"}, {"code": "MX"}]},
            ]),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home", features=["shipping"],
        )
        assert result["results"]["shipping"]["fully_covered"] is True
        assert result["results"]["shipping"]["gap_countries"] == []

    def test_recommendation_metafield_saved(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses=self._responses([]),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="beauty", features=["shipping"],
        )
        assert result["results"]["shipping"]["saved"] is True
        mf_bodies = [b for m, p, b in calls if m == "POST" and p == "metafields.json"]
        ship_body = next(b for b in mf_bodies if b["metafield"]["key"] == "shipping")
        program = json.loads(ship_body["metafield"]["value"])
        assert program["niche"] == "beauty"
        assert len(program["recommended_zones"]) == 1  # beauty has 1 worldwide zone
        assert program["recommended_zones"][0]["name"] == "Worldwide"
        # Worldwide zone has free-over-50 + standard
        rates = program["recommended_zones"][0]["rates"]
        assert len(rates) == 2

    def test_unknown_niche_falls_back_to_general(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._responses([]),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="zzz", features=["shipping"],
        )
        assert result["results"]["shipping"]["recommended_zones"] == 2  # general


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
    def _patch_router(
        self, monkeypatch, existing_titles=None,
    ):
        """Same router-boundary patch as TestDiscounts.
        Returns the call list for assertion."""
        calls: list[tuple[str, dict]] = []

        class FakeResult:
            def __init__(self, ok=True, data=None, error=""):
                self.ok = ok
                self.data = data or {}
                self.error = error

        class FakeRouter:
            def execute(self_inner, capability, params):
                cap_name = (
                    capability.value
                    if hasattr(capability, "value")
                    else str(capability)
                )
                calls.append((cap_name, dict(params)))
                if cap_name == "shopify_list_discounts":
                    return FakeResult(data={
                        "discounts": [
                            {"title": t}
                            for t in (existing_titles or [])
                        ],
                    })
                if cap_name == "shopify_create_discount":
                    return FakeResult(data={
                        "discount_id": "gid://x/1",
                    })
                if cap_name == (
                    "shopify_create_discount_free_shipping"
                ):
                    return FakeResult(data={
                        "id": "gid://x/2",
                    })
                return FakeResult(ok=False)

        fake_router = FakeRouter()
        monkeypatch.setattr(
            "core.adapters.get_router",
            lambda: fake_router,
        )
        monkeypatch.setattr(
            "core.adapters.router.get_router",
            lambda: fake_router,
        )
        return calls

    def test_creates_friend10_and_metafield(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "POST metafields.json": {"metafield": {"id": 1}},
            },
        )
        router_calls = self._patch_router(monkeypatch)
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", features=["referral"],
        )
        r = result["results"]["referral"]
        assert r["saved"] is True
        assert r["discount_code"] == "FRIEND10"
        assert r["code_created"] is True
        # FRIEND10 went through the router create path
        codes = {
            params.get("code")
            for cap, params in router_calls
            if cap == "shopify_create_discount"
        }
        assert "FRIEND10" in codes

    def test_skips_rule_creation_if_exists(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses={
                "POST metafields.json": {"metafield": {"id": 1}},
            },
        )
        router_calls = self._patch_router(
            monkeypatch, existing_titles=["FRIEND10"],
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", features=["referral"],
        )
        assert result["results"]["referral"]["code_created"] is False
        assert result["results"]["referral"]["saved"] is True  # metafield still saved
        # No create_discount call fired for FRIEND10
        creates = [
            params for cap, params in router_calls
            if cap == "shopify_create_discount"
            and params.get("code") == "FRIEND10"
        ]
        assert not creates

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


class TestEmails:
    def test_saves_all_four_templates(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={"POST metafields.json": {"metafield": {"id": 1}}},
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            store_name="Cozy Corner",
            features=["emails"],
        )
        e = result["results"]["emails"]
        assert e["saved"] is True
        assert e["template_count"] == 4
        assert set(e["templates"]) == {
            "order_confirmation", "shipping_update",
            "abandoned_cart", "win_back",
        }

    def test_metafield_body_has_full_templates(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={"POST metafields.json": {"metafield": {"id": 1}}},
        )
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="beauty",
            store_name="Glow Co",
            features=["emails"],
        )
        mf_bodies = [b for m, p, b in calls if p == "metafields.json" and m == "POST"]
        email_body = next(b for b in mf_bodies if b["metafield"]["key"] == "emails")
        program = json.loads(email_body["metafield"]["value"])
        assert program["niche"] == "beauty"
        templates = program["templates"]
        for key in ("order_confirmation", "shipping_update",
                    "abandoned_cart", "win_back"):
            t = templates[key]
            assert t["subject"]
            assert t["preheader"]
            assert t["trigger"]
            assert "delay_hours" in t
            assert t["body_html"].startswith("<div")

    def test_niche_tone_in_template_body(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={"POST metafields.json": {"metafield": {"id": 1}}},
        )
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="beauty",
            features=["emails"],
        )
        mf_bodies = [b for m, p, b in calls if p == "metafields.json" and m == "POST"]
        program = json.loads(next(
            b for b in mf_bodies if b["metafield"]["key"] == "emails"
        )["metafield"]["value"])
        # Beauty tone: "Hi gorgeous," in greeting
        body = program["templates"]["order_confirmation"]["body_html"]
        assert "Hi gorgeous," in body
        assert "Stay radiant," in body
        # Beauty adj = "glow-worthy"
        shipping_body = program["templates"]["shipping_update"]["body_html"]
        assert "glow-worthy" in shipping_body

    def test_abandoned_cart_has_delay(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={"POST metafields.json": {"metafield": {"id": 1}}},
        )
        c = _make()
        c.configure("x.myshopify.com", "tok", features=["emails"])
        mf_bodies = [b for m, p, b in calls if p == "metafields.json" and m == "POST"]
        program = json.loads(mf_bodies[0]["metafield"]["value"])
        cart = program["templates"]["abandoned_cart"]
        assert cart["delay_hours"] == 1
        assert "COMEBACK10" in cart["body_html"]

    def test_win_back_delayed_60_days(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={"POST metafields.json": {"metafield": {"id": 1}}},
        )
        c = _make()
        c.configure("x.myshopify.com", "tok", features=["emails"])
        mf_bodies = [b for m, p, b in calls if p == "metafields.json" and m == "POST"]
        program = json.loads(mf_bodies[0]["metafield"]["value"])
        wb = program["templates"]["win_back"]
        assert wb["delay_hours"] == 60 * 24
        assert "WELCOME15" in wb["body_html"]

    def test_placeholders_present(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={"POST metafields.json": {"metafield": {"id": 1}}},
        )
        c = _make()
        c.configure("x.myshopify.com", "tok", features=["emails"])
        mf_bodies = [b for m, p, b in calls if p == "metafields.json" and m == "POST"]
        program = json.loads(mf_bodies[0]["metafield"]["value"])
        # Order confirmation references {{order_number}} + {{order_status_url}}
        oc = program["templates"]["order_confirmation"]["body_html"]
        assert "{{order_number}}" in oc
        assert "{{order_status_url}}" in oc
        # Shipping references {{tracking_url}}
        assert "{{tracking_url}}" in program["templates"]["shipping_update"]["body_html"]

    def test_store_name_fallback(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses={"POST metafields.json": {"metafield": {"id": 1}}},
        )
        c = _make()
        c.configure("x.myshopify.com", "tok", features=["emails"])  # no store_name
        mf_bodies = [b for m, p, b in calls if p == "metafields.json" and m == "POST"]
        program = json.loads(mf_bodies[0]["metafield"]["value"])
        # Fallback to "Our Store"
        assert "Our Store" in program["templates"]["order_confirmation"]["subject"]


class TestPayments:
    def _responses(self, gateway_names_per_order=None, shop=None):
        orders = [
            {"payment_gateway_names": names}
            for names in (gateway_names_per_order or [])
        ]
        return {
            "GET orders.json": {"orders": orders},
            "GET shop.json": {"shop": shop or {"country_code": "US", "currency": "USD"}},
            "POST metafields.json": {"metafield": {"id": 1}},
        }

    def test_detects_active_gateways_from_orders(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._responses(
                gateway_names_per_order=[
                    ["shopify_payments"],
                    ["paypal"],
                    ["shopify_payments", "shop_pay"],
                ],
            ),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["payments"],
        )
        p = result["results"]["payments"]
        assert set(p["active_gateways"]) == {"shopify_payments", "paypal", "shop_pay"}
        assert p["active_count"] == 3
        # Home niche recommends 5 gateways; we have 3 → 2 missing
        assert p["missing_count"] == 2
        assert "apple_pay" in p["missing_gateways"]
        assert "google_pay" in p["missing_gateways"]

    def test_no_orders_means_no_active_gateways(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._responses(gateway_names_per_order=[]),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["payments"],
        )
        assert result["results"]["payments"]["active_count"] == 0
        assert result["results"]["payments"]["missing_count"] == 5

    def test_gateway_names_normalized(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._responses(
                gateway_names_per_order=[
                    ["Shopify Payments"],  # capitalized + space
                    ["PayPal"],
                ],
            ),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["payments"],
        )
        assert "shopify_payments" in result["results"]["payments"]["active_gateways"]
        assert "paypal" in result["results"]["payments"]["active_gateways"]

    def test_fashion_niche_recommends_klarna_afterpay(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._responses(
                gateway_names_per_order=[["shopify_payments"]],
            ),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="fashion",
            features=["payments"],
        )
        missing = result["results"]["payments"]["missing_gateways"]
        assert "klarna" in missing
        assert "afterpay" in missing

    def test_shop_country_and_currency_captured(self, monkeypatch):
        _install_fake_client(
            monkeypatch,
            responses=self._responses(
                gateway_names_per_order=[],
                shop={"country_code": "DE", "currency": "EUR"},
            ),
        )
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", niche="tech",
            features=["payments"],
        )
        assert result["results"]["payments"]["country"] == "DE"
        assert result["results"]["payments"]["currency"] == "EUR"

    def test_metafield_body_contains_program(self, monkeypatch):
        calls = _install_fake_client(
            monkeypatch,
            responses=self._responses(
                gateway_names_per_order=[["shopify_payments"]],
            ),
        )
        c = _make()
        c.configure(
            "x.myshopify.com", "tok", niche="home",
            features=["payments"],
        )
        mf_bodies = [b for m, p, b in calls if p == "metafields.json" and m == "POST"]
        pay_body = next(b for b in mf_bodies if b["metafield"]["key"] == "payments")
        program = json.loads(pay_body["metafield"]["value"])
        assert program["niche"] == "home"
        assert program["active_gateways"] == ["shopify_payments"]
        assert "apple_pay" in program["missing_gateways"]

    def test_saved_flag_true(self, monkeypatch):
        _install_fake_client(monkeypatch, responses=self._responses())
        c = _make()
        result = c.configure(
            "x.myshopify.com", "tok", features=["payments"],
        )
        assert result["results"]["payments"]["saved"] is True


class TestAllFeaturesIncludesNewOnes:
    def test_all_features_count(self):
        from execution.store_configurator import ALL_FEATURES
        for name in ("gifts", "loyalty", "referral", "emails", "payments"):
            assert name in ALL_FEATURES
        assert len(ALL_FEATURES) == 11


class TestConfigureCLI:
    """End-to-end tests for `shopai store configure`."""

    def _setup_store(self, tmp_path, monkeypatch):
        """Create a real StoreManager with one test store."""
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        db_path = str(tmp_path / "shopai.db")
        db = ShopAIDatabase(db_path)
        sm = StoreManager(db)
        sm.add_store("teststore", "teststore.myshopify.com",
                     api_key="shpat_testtoken", niche="home")

        import cli
        monkeypatch.setattr(cli, "_get_store_manager", lambda: sm)
        return sm

    def test_configure_dry_run_prints_plan(self, tmp_path, monkeypatch, capsys):
        self._setup_store(tmp_path, monkeypatch)
        _install_fake_client(monkeypatch)

        import cli
        cli.main(["store", "configure", "teststore", "--dry-run", "--only", "collections"])
        out = capsys.readouterr().out
        assert "Dry-run" in out
        assert "teststore" in out
        assert "home" in out
        assert "Status: planned" in out
        assert "collections" in out
        assert "Planned writes" in out

    def test_configure_dry_run_all_features(self, tmp_path, monkeypatch, capsys):
        self._setup_store(tmp_path, monkeypatch)
        _install_fake_client(monkeypatch)

        import cli
        cli.main(["store", "configure", "teststore", "--dry-run"])
        out = capsys.readouterr().out
        assert "Status: planned" in out
        # Summary should include every feature
        for feature in ("collections", "discounts", "shipping", "content",
                        "product_tags", "ai_config", "gifts", "loyalty",
                        "referral", "emails", "payments"):
            assert feature in out

    def test_configure_respects_only_filter(self, tmp_path, monkeypatch, capsys):
        self._setup_store(tmp_path, monkeypatch)
        _install_fake_client(monkeypatch)

        import cli
        cli.main([
            "store", "configure", "teststore",
            "--dry-run", "--only", "discounts,emails",
        ])
        out = capsys.readouterr().out
        assert "discounts" in out
        assert "emails" in out
        # Content shouldn't appear as a feature result line
        lines = out.splitlines()
        # Collect the feature lines (indented after "Feature results:")
        in_features = False
        feature_names = []
        for line in lines:
            if line.strip().startswith("Feature results:"):
                in_features = True
                continue
            if in_features:
                if not line.startswith("  "):
                    break
                feature_names.append(line.strip().split()[0])
        assert "discounts" in feature_names
        assert "emails" in feature_names
        assert "collections" not in feature_names

    def test_configure_niche_override(self, tmp_path, monkeypatch, capsys):
        self._setup_store(tmp_path, monkeypatch)
        _install_fake_client(monkeypatch)

        import cli
        cli.main([
            "store", "configure", "teststore",
            "--dry-run", "--niche", "beauty", "--only", "collections",
        ])
        out = capsys.readouterr().out
        assert "Niche:  beauty" in out

    def test_configure_uses_active_store_by_default(
        self, tmp_path, monkeypatch, capsys,
    ):
        sm = self._setup_store(tmp_path, monkeypatch)
        # teststore is the only store, should be active
        assert sm.active_store_id == "teststore"
        _install_fake_client(monkeypatch)

        import cli
        cli.main(["store", "configure", "--dry-run", "--only", "ai_config"])
        out = capsys.readouterr().out
        assert "teststore" in out
        assert "Status: planned" in out

    def test_configure_missing_store_reports_error(
        self, tmp_path, monkeypatch, capsys,
    ):
        sm = self._setup_store(tmp_path, monkeypatch)
        _install_fake_client(monkeypatch)
        # ``StoreManager.get_credentials`` falls back to env-var
        # creds for unknown stores. A dev machine with ``.env``
        # loaded (or any shell-level shopify creds) would
        # accidentally return a real shop_url for "ghost" and
        # the test would pass through the credential check.
        # Stub the StoreManager method directly so the test
        # surfaces the "not found" error regardless of host env.
        original_get_credentials = sm.get_credentials

        def _gated_get_credentials(store_id=""):
            if store_id == "ghost":
                return None
            return original_get_credentials(store_id)

        monkeypatch.setattr(sm, "get_credentials", _gated_get_credentials)

        import cli
        cli.main(["store", "configure", "ghost", "--dry-run"])
        out = capsys.readouterr().out
        assert "not found" in out.lower() or "no usable credentials" in out.lower()


class TestSingleton:
    def test_get_store_configurator_returns_singleton(self):
        from execution import store_configurator as mod
        mod._instance = None
        a = mod.get_store_configurator()
        b = mod.get_store_configurator()
        assert a is b
