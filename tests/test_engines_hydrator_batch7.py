"""Tests for batch-7 of engines wired to the shared Shopify hydrator.

Two newly-mappable Shopify resources go gated; three engines pick
up auxiliary product hydration:

  - returns_management   gated on returns      → SHOPIFY_LIST_RETURNS
  - gift_card            gated on gift_cards   → SHOPIFY_LIST_GIFT_CARDS
  - brand_identity       aux products          → SHOPIFY_LIST_PRODUCTS
                         (gated on business.name)
  - campaign_strategy    aux products          → SHOPIFY_LIST_PRODUCTS
                         (gated on goal/budget/channels)
  - competition_analyzer aux products          → SHOPIFY_LIST_PRODUCTS
                         (gated on competitors)

Auxiliary engines (the last three) hydrate products as enrichment —
even though products is NOT gated, downstream stages USE it, so an
empty list weakens the result. Tests cover that hydrate is invoked
and the standard guard for the actual gated input still fires.
"""
from __future__ import annotations

from unittest.mock import patch


# ─── Shared fixtures ──────────────────────────────────────────────


def _product_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/Product/{i}",
            "title": f"P{i}",
            "price": 10.0 + i,
        }
        for i in range(1, n + 1)
    ]


def _return_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/Return/{i}",
            "status": "REQUESTED",
            "order_id": f"gid://shopify/Order/{i}",
            "items": [{"line_item_id": f"li{i}", "qty": 1}],
        }
        for i in range(1, n + 1)
    ]


def _gift_card_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/GiftCard/{i}",
            "balance": 50.0,
            "initial_value": 100.0,
            "status": "ACTIVE",
        }
        for i in range(1, n + 1)
    ]


# ─── returns_management (returns gated) ──────────────────────────


class TestReturnsManagementHydration:

    def test_hydrate_fills_empty_returns(self):
        from engines.returns_management.flow import (
            ReturnsManagementEngine,
        )

        with patch(
            "engines.returns_management.flow.hydrate",
            return_value=_return_fixture(2),
        ):
            output = ReturnsManagementEngine().run({
                "data": {"returns": []},
            })

        if output["status"] == "error":
            assert "Returns list is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.returns_management.flow import (
            ReturnsManagementEngine,
        )

        with patch(
            "engines.returns_management.flow.hydrate",
            return_value=[],
        ):
            output = ReturnsManagementEngine().run({
                "data": {"returns": []},
            })

        assert output["status"] == "error"
        assert "Returns list is required" in output["error"]

    def test_hydrate_uses_returns_capability(self):
        from engines.returns_management.flow import (
            ReturnsManagementEngine,
        )

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _return_fixture(1)

        with patch(
            "engines.returns_management.flow.hydrate",
            side_effect=_spy,
        ):
            ReturnsManagementEngine().run({
                "data": {"returns": []},
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_RETURNS"
        assert captured["list_field"] == "returns"


# ─── gift_card (gift_cards gated) ────────────────────────────────


class TestGiftCardHydration:

    def test_hydrate_fills_empty_gift_cards(self):
        from engines.gift_card.flow import GiftCardEngine

        with patch(
            "engines.gift_card.flow.hydrate",
            return_value=_gift_card_fixture(2),
        ):
            output = GiftCardEngine().run({
                "data": {"gift_cards": []},
            })

        if output["status"] == "error":
            assert "Gift cards list is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.gift_card.flow import GiftCardEngine

        with patch(
            "engines.gift_card.flow.hydrate",
            return_value=[],
        ):
            output = GiftCardEngine().run({
                "data": {"gift_cards": []},
            })

        assert output["status"] == "error"
        assert "Gift cards list is required" in output["error"]

    def test_hydrate_uses_gift_cards_capability(self):
        from engines.gift_card.flow import GiftCardEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _gift_card_fixture(1)

        with patch(
            "engines.gift_card.flow.hydrate",
            side_effect=_spy,
        ):
            GiftCardEngine().run({
                "data": {"gift_cards": []},
            })

        assert captured["capability_name"] == \
            "SHOPIFY_LIST_GIFT_CARDS"
        assert captured["list_field"] == "gift_cards"


# ─── brand_identity (products auxiliary) ─────────────────────────


class TestBrandIdentityHydration:

    def test_hydrate_invoked_for_products(self):
        from engines.brand_identity.flow import BrandIdentityEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _product_fixture(2)

        with patch(
            "engines.brand_identity.flow.hydrate",
            side_effect=_spy,
        ):
            BrandIdentityEngine().run({
                "data": {
                    "business": {"name": "Acme"},
                    "products": [],
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"

    def test_business_guard_still_fires_when_business_missing(self):
        # The auxiliary hydration must NOT bypass the gated
        # business-name guard. That guard fires BEFORE hydrate now,
        # so hydrate isn't called when business is missing.
        from engines.brand_identity.flow import BrandIdentityEngine

        with patch(
            "engines.brand_identity.flow.hydrate",
        ) as mock_hydrate:
            output = BrandIdentityEngine().run({
                "data": {"business": {}, "products": []},
            })

        assert output["status"] == "error"
        assert "Business info with 'name' is required" \
            in output["error"]
        mock_hydrate.assert_not_called()


# ─── campaign_strategy (products auxiliary) ──────────────────────


class TestCampaignStrategyHydration:

    def test_hydrate_invoked_for_products(self):
        from engines.campaign_strategy.flow import (
            CampaignStrategyEngine,
        )

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _product_fixture(2)

        with patch(
            "engines.campaign_strategy.flow.hydrate",
            side_effect=_spy,
        ):
            CampaignStrategyEngine().run({
                "data": {
                    "goal": "boost_revenue",
                    "budget": 1000,
                    "channels": ["email"],
                    "products": [],
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"

    def test_goal_guard_still_fires(self):
        from engines.campaign_strategy.flow import (
            CampaignStrategyEngine,
        )

        # Hydrate fills products, but goal is missing → that guard
        # still fires.
        with patch(
            "engines.campaign_strategy.flow.hydrate",
            return_value=_product_fixture(1),
        ):
            output = CampaignStrategyEngine().run({
                "data": {
                    "goal": "",
                    "budget": 1000,
                    "channels": ["email"],
                    "products": [],
                },
            })

        assert output["status"] == "error"
        assert "Campaign goal is required" in output["error"]


# ─── competition_analyzer (products auxiliary) ──────────────────


class TestCompetitionAnalyzerHydration:

    def test_hydrate_invoked_for_products(self):
        from engines.competition_analyzer.flow import (
            CompetitionAnalyzerEngine,
        )

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _product_fixture(2)

        with patch(
            "engines.competition_analyzer.flow.hydrate",
            side_effect=_spy,
        ):
            CompetitionAnalyzerEngine().run({
                "data": {
                    "competitors": [
                        {"id": "c1", "name": "Comp1"},
                    ],
                    "products": [],
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"

    def test_competitors_guard_still_fires(self):
        # Hydrate fills products, but competitors is empty → that
        # guard still fires.
        from engines.competition_analyzer.flow import (
            CompetitionAnalyzerEngine,
        )

        with patch(
            "engines.competition_analyzer.flow.hydrate",
            return_value=_product_fixture(1),
        ):
            output = CompetitionAnalyzerEngine().run({
                "data": {"competitors": [], "products": []},
            })

        assert output["status"] == "error"
        assert "Competitors list is required" in output["error"]
