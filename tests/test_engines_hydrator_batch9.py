"""Tests for batch-9 of engines wired to the shared Shopify hydrator.

Final batch (auxiliary product hydration):

  - email_marketing  products aux  (gated on audience_segments)
  - social_media     products aux  (gated on platforms + brand)
  - store_design     products aux  (gated on brand)

email_marketing and social_media use the parsed-dict shape (a
``_validate_input`` helper that returns dict|None). Hydration runs
AFTER validation succeeds and re-reads ``hydrate_limit`` /
``hydrate_query`` from the raw input payload, since the parsed
dict doesn't carry them through.
"""
from __future__ import annotations

from unittest.mock import patch


def _product_fixture(n: int = 2) -> list[dict]:
    return [
        {"id": f"gid://shopify/Product/{i}", "title": f"P{i}",
         "price": 10.0 + i}
        for i in range(1, n + 1)
    ]


# ─── store_design ─────────────────────────────────────────────────


class TestStoreDesignHydration:

    def test_hydrate_invoked_for_products(self):
        from engines.store_design.flow import StoreDesignEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _product_fixture(2)

        with patch(
            "engines.store_design.flow.hydrate",
            side_effect=_spy,
        ):
            StoreDesignEngine().run({
                "data": {
                    "brand": {"name": "Acme"},
                    "products": [],
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"

    def test_hydrate_kwargs_threaded(self):
        from engines.store_design.flow import StoreDesignEngine

        captured: dict = {}

        def _spy(*, limit=None, query=None, **_):
            captured["limit"] = limit
            captured["query"] = query
            return _product_fixture(1)

        with patch(
            "engines.store_design.flow.hydrate",
            side_effect=_spy,
        ):
            StoreDesignEngine().run({
                "data": {
                    "brand": {"name": "Acme"},
                    "products": [],
                    "hydrate_limit": 12,
                    "hydrate_query": "tag:b9",
                },
            })

        assert captured["limit"] == 12
        assert captured["query"] == "tag:b9"


# ─── email_marketing (parsed-dict shape) ─────────────────────────


class TestEmailMarketingHydration:

    def test_hydrate_invoked_for_products(self):
        from engines.email_marketing.flow import EmailMarketingEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _product_fixture(2)

        with patch(
            "engines.email_marketing.flow.hydrate",
            side_effect=_spy,
        ):
            EmailMarketingEngine().run({
                "data": {
                    "goal": "boost_revenue",
                    "audience_segments": ["loyal"],
                    "products": [],
                    "store_name": "Acme",
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"

    def test_audience_segments_guard_still_fires(self):
        # Validation fails BEFORE hydrate is ever called.
        from engines.email_marketing.flow import EmailMarketingEngine

        with patch(
            "engines.email_marketing.flow.hydrate",
        ) as mock_hydrate:
            output = EmailMarketingEngine().run({
                "data": {
                    "goal": "",
                    "audience_segments": [],
                    "products": [],
                },
            })

        assert output["status"] == "fail"
        mock_hydrate.assert_not_called()

    def test_hydrate_kwargs_re_read_from_raw_input(self):
        # _validate_input doesn't carry hydrate kwargs through;
        # the engine re-reads them from input_payload.data.
        from engines.email_marketing.flow import EmailMarketingEngine

        captured: dict = {}

        def _spy(*, limit=None, query=None, **_):
            captured["limit"] = limit
            captured["query"] = query
            return _product_fixture(1)

        with patch(
            "engines.email_marketing.flow.hydrate",
            side_effect=_spy,
        ):
            EmailMarketingEngine().run({
                "data": {
                    "goal": "win_back",
                    "audience_segments": ["lapsed"],
                    "products": [],
                    "hydrate_limit": 99,
                    "hydrate_query": "tag:flash",
                },
            })

        assert captured["limit"] == 99
        assert captured["query"] == "tag:flash"


# ─── social_media (parsed-dict shape) ────────────────────────────


class TestSocialMediaHydration:

    def test_hydrate_invoked_for_products(self):
        from engines.social_media.flow import SocialMediaEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _product_fixture(2)

        with patch(
            "engines.social_media.flow.hydrate",
            side_effect=_spy,
        ):
            SocialMediaEngine().run({
                "data": {
                    "platforms": ["instagram"],
                    "brand": {"name": "Acme", "voice": "fun"},
                    "products": [],
                    "goal": "engagement",
                    "posting_frequency": "daily",
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"

    def test_platforms_guard_still_fires(self):
        from engines.social_media.flow import SocialMediaEngine

        with patch(
            "engines.social_media.flow.hydrate",
        ) as mock_hydrate:
            output = SocialMediaEngine().run({
                "data": {
                    "platforms": [],
                    "brand": {"name": "Acme"},
                    "products": [],
                },
            })

        assert output["status"] == "fail"
        mock_hydrate.assert_not_called()

    def test_hydrate_kwargs_re_read_from_raw_input(self):
        from engines.social_media.flow import SocialMediaEngine

        captured: dict = {}

        def _spy(*, limit=None, query=None, **_):
            captured["limit"] = limit
            captured["query"] = query
            return _product_fixture(1)

        with patch(
            "engines.social_media.flow.hydrate",
            side_effect=_spy,
        ):
            SocialMediaEngine().run({
                "data": {
                    "platforms": ["tiktok"],
                    "brand": {"name": "Acme"},
                    "products": [],
                    "hydrate_limit": 7,
                    "hydrate_query": "tag:viral",
                },
            })

        assert captured["limit"] == 7
        assert captured["query"] == "tag:viral"
