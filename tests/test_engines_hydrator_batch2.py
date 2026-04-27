"""Tests for batch-2 of engines wired to the shared Shopify hydrator.

Five more engines now consume `engines._shopify_hydrator.hydrate`
to auto-fetch their primary input list when callers leave it empty:

  - affiliate     (products)
  - dropshipping  (orders)
  - financial     (orders)
  - order_quality (orders)
  - monetization  (products + customers)

Tests follow the same shape as batch1: patch
``engines.<engine>.flow.hydrate`` and verify (a) auto-fill happens
when supplied is empty, (b) the standard "list is required" guard
still fires when both supplied + hydrated are empty, and
(c) ``hydrate_limit`` / ``hydrate_query`` are threaded through.
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
            "cogs": 5.0,
            "daily_sales": 1.0 + i,
        }
        for i in range(1, n + 1)
    ]


def _order_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/Order/{i}",
            "customer_id": f"gid://shopify/Customer/{i}",
            "total": 50.0,
            "line_items": [
                {"product_id": f"gid://shopify/Product/{i}",
                 "quantity": 1, "price": 50.0},
            ],
        }
        for i in range(1, n + 1)
    ]


def _customer_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/Customer/{i}",
            "total_orders": i,
            "total_spent": 100.0 * i,
        }
        for i in range(1, n + 1)
    ]


# ─── affiliate ────────────────────────────────────────────────────


class TestAffiliateHydration:

    def test_hydrate_fills_empty_products(self):
        from engines.affiliate.flow import AffiliateEngine

        with patch(
            "engines.affiliate.flow.hydrate",
            return_value=_product_fixture(2),
        ):
            output = AffiliateEngine().run({
                "data": {"products": []},
            })

        if output["status"] == "error":
            assert "Product list is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.affiliate.flow import AffiliateEngine

        with patch(
            "engines.affiliate.flow.hydrate",
            return_value=[],
        ):
            output = AffiliateEngine().run({
                "data": {"products": []},
            })
        assert output["status"] == "error"
        assert "Product list is required" in output["error"]

    def test_hydrate_kwargs_threaded(self):
        from engines.affiliate.flow import AffiliateEngine

        captured: dict = {}

        def _spy(*, capability_name, limit=None, query=None, **_):
            captured["capability_name"] = capability_name
            captured["limit"] = limit
            captured["query"] = query
            return _product_fixture(1)

        with patch(
            "engines.affiliate.flow.hydrate",
            side_effect=_spy,
        ):
            AffiliateEngine().run({
                "data": {
                    "products": [],
                    "hydrate_limit": 60,
                    "hydrate_query": "tag:affiliate",
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["limit"] == 60
        assert captured["query"] == "tag:affiliate"


# ─── dropshipping ─────────────────────────────────────────────────


class TestDropshippingHydration:

    def test_hydrate_fills_empty_orders(self):
        from engines.dropshipping.flow import DropshippingEngine

        with patch(
            "engines.dropshipping.flow.hydrate",
            return_value=_order_fixture(2),
        ):
            output = DropshippingEngine().run({
                "data": {"orders": []},
            })

        if output["status"] == "error":
            assert "Orders list is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.dropshipping.flow import DropshippingEngine

        with patch(
            "engines.dropshipping.flow.hydrate",
            return_value=[],
        ):
            output = DropshippingEngine().run({
                "data": {"orders": []},
            })
        assert output["status"] == "error"
        assert "Orders list is required" in output["error"]

    def test_hydrate_uses_orders_capability(self):
        from engines.dropshipping.flow import DropshippingEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, limit=None,
                 query=None, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            captured["limit"] = limit
            captured["query"] = query
            return _order_fixture(1)

        with patch(
            "engines.dropshipping.flow.hydrate",
            side_effect=_spy,
        ):
            DropshippingEngine().run({
                "data": {
                    "orders": [],
                    "hydrate_limit": 75,
                    "hydrate_query": "fulfillment_status:unfulfilled",
                },
            })

        assert captured["capability_name"] == "SHOPIFY_FETCH_ORDERS"
        assert captured["list_field"] == "orders"
        assert captured["limit"] == 75
        assert captured["query"] == \
            "fulfillment_status:unfulfilled"

    def test_non_list_orders_coerced_before_hydrate(self):
        from engines.dropshipping.flow import DropshippingEngine

        captured: dict = {}

        def _spy(*, supplied, **_):
            captured["supplied"] = supplied
            return []

        with patch(
            "engines.dropshipping.flow.hydrate",
            side_effect=_spy,
        ):
            DropshippingEngine().run({
                "data": {"orders": "not-a-list"},
            })

        assert captured["supplied"] == []


# ─── financial ────────────────────────────────────────────────────


class TestFinancialHydration:

    def test_hydrate_fills_empty_orders(self):
        from engines.financial.flow import FinancialEngine

        with patch(
            "engines.financial.flow.hydrate",
            return_value=_order_fixture(2),
        ):
            output = FinancialEngine().run({
                "data": {"orders": []},
            })

        if output["status"] == "error":
            assert "Orders list is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.financial.flow import FinancialEngine

        with patch(
            "engines.financial.flow.hydrate",
            return_value=[],
        ):
            output = FinancialEngine().run({
                "data": {"orders": []},
            })
        assert output["status"] == "error"
        assert "Orders list is required" in output["error"]

    def test_hydrate_uses_orders_capability(self):
        from engines.financial.flow import FinancialEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _order_fixture(1)

        with patch(
            "engines.financial.flow.hydrate",
            side_effect=_spy,
        ):
            FinancialEngine().run({
                "data": {"orders": []},
            })

        assert captured["capability_name"] == "SHOPIFY_FETCH_ORDERS"
        assert captured["list_field"] == "orders"


# ─── order_quality ────────────────────────────────────────────────


class TestOrderQualityHydration:

    def test_hydrate_fills_empty_orders(self):
        from engines.order_quality.flow import OrderQualityEngine

        with patch(
            "engines.order_quality.flow.hydrate",
            return_value=_order_fixture(2),
        ):
            output = OrderQualityEngine().run({
                "data": {"orders": []},
            })

        if output["status"] == "error":
            assert "Orders list is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.order_quality.flow import OrderQualityEngine

        with patch(
            "engines.order_quality.flow.hydrate",
            return_value=[],
        ):
            output = OrderQualityEngine().run({
                "data": {"orders": []},
            })
        assert output["status"] == "error"
        assert "Orders list is required" in output["error"]

    def test_hydrate_kwargs_threaded(self):
        from engines.order_quality.flow import OrderQualityEngine

        captured: dict = {}

        def _spy(*, capability_name, limit=None, query=None, **_):
            captured["capability_name"] = capability_name
            captured["limit"] = limit
            captured["query"] = query
            return _order_fixture(1)

        with patch(
            "engines.order_quality.flow.hydrate",
            side_effect=_spy,
        ):
            OrderQualityEngine().run({
                "data": {
                    "orders": [],
                    "hydrate_limit": 40,
                    "hydrate_query": "tag:defective",
                },
            })

        assert captured["capability_name"] == "SHOPIFY_FETCH_ORDERS"
        assert captured["limit"] == 40
        assert captured["query"] == "tag:defective"


# ─── monetization (products + customers) ─────────────────────────


class TestMonetizationHydration:

    def test_hydrates_both_products_and_customers(self):
        from engines.monetization.flow import MonetizationEngine

        capabilities_seen: list[str] = []

        def _spy(*, capability_name, list_field, **_):
            capabilities_seen.append(capability_name)
            if list_field == "products":
                return _product_fixture(2)
            if list_field == "customers":
                return _customer_fixture(2)
            return []

        with patch(
            "engines.monetization.flow.hydrate",
            side_effect=_spy,
        ):
            output = MonetizationEngine().run({
                "data": {"products": [], "customers": []},
            })

        assert "SHOPIFY_LIST_PRODUCTS" in capabilities_seen
        assert "SHOPIFY_FETCH_CUSTOMERS" in capabilities_seen
        if output["status"] == "error":
            assert "Products list is required" not in (
                output.get("error") or ""
            )

    def test_empty_products_falls_through(self):
        from engines.monetization.flow import MonetizationEngine

        def _spy(*, list_field, **_):
            if list_field == "customers":
                return _customer_fixture(1)
            return []  # products empty → guard fires

        with patch(
            "engines.monetization.flow.hydrate",
            side_effect=_spy,
        ):
            output = MonetizationEngine().run({
                "data": {"products": [], "customers": []},
            })

        assert output["status"] == "error"
        assert "Products list is required" in output["error"]

    def test_hydrate_kwargs_shared_between_calls(self):
        from engines.monetization.flow import MonetizationEngine

        seen_limits: list = []
        seen_queries: list = []

        def _spy(*, list_field, limit=None, query=None, **_):
            seen_limits.append(limit)
            seen_queries.append(query)
            if list_field == "products":
                return _product_fixture(1)
            return _customer_fixture(1)

        with patch(
            "engines.monetization.flow.hydrate",
            side_effect=_spy,
        ):
            MonetizationEngine().run({
                "data": {
                    "products": [],
                    "customers": [],
                    "hydrate_limit": 25,
                    "hydrate_query": "tag:premium",
                },
            })

        # Both calls saw the same kwargs.
        assert seen_limits == [25, 25]
        assert seen_queries == ["tag:premium", "tag:premium"]
