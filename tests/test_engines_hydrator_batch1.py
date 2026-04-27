"""Tests for batch-1 of engines wired to the shared Shopify hydrator.

Five engines now consume `engines._shopify_hydrator.hydrate` to
auto-fetch products / customers / orders when callers leave the
input lists empty:

  - discount_strategy   (products)
  - dynamic_pricing     (products)
  - customer_segmentation (customers)
  - loyalty             (customers + orders)
  - inventory           (products)

Each engine uses the shared core directly — no per-engine wrapper
module — so tests patch `engines.<engine>.flow.hydrate` to verify:

  1. The flow calls `hydrate` (with the right capability + kwargs).
  2. When `hydrate` returns a non-empty list, the standard
     "list is required" guard does NOT fire (graceful auto-fill).
  3. When `hydrate` returns empty AND the caller supplied nothing,
     the original error message still fires (graceful degradation).
  4. `hydrate_limit` / `hydrate_query` are threaded through.
"""
from __future__ import annotations

from unittest.mock import patch


# ─── Shared fixtures ──────────────────────────────────────────────


def _product_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/Product/{i}",
            "title": f"P{i}",
            "current_price": 10.0 + i,
            "cogs": 5.0,
            "daily_sales": 1.0 + i,
        }
        for i in range(1, n + 1)
    ]


def _customer_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/Customer/{i}",
            "first_purchase": "2024-01-01",
            "last_purchase": "2025-01-01",
            "total_orders": i,
            "total_spent": 100.0 * i,
            "avg_order_value": 50.0,
            "days_since_last": 30,
            "categories_bought": ["a"],
            "email_opens": 2,
            "cart_abandons": 0,
        }
        for i in range(1, n + 1)
    ]


def _order_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/Order/{i}",
            "customer_id": f"gid://shopify/Customer/{i}",
            "total": 50.0,
        }
        for i in range(1, n + 1)
    ]


# ─── discount_strategy ────────────────────────────────────────────


class TestDiscountStrategyHydration:

    def test_hydrate_fills_empty_products(self):
        from engines.discount_strategy.flow import DiscountStrategyEngine

        injected = _product_fixture(2)

        with patch(
            "engines.discount_strategy.flow.hydrate",
            return_value=injected,
        ):
            output = DiscountStrategyEngine().run({
                "data": {"products": []},
            })

        # Auto-fill succeeded → "Products list is required" must
        # NOT be the failure reason.
        if output["status"] == "error":
            assert "Products list is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.discount_strategy.flow import DiscountStrategyEngine

        with patch(
            "engines.discount_strategy.flow.hydrate",
            return_value=[],
        ):
            output = DiscountStrategyEngine().run({
                "data": {"products": []},
            })
        assert output["status"] == "error"
        assert "Products list is required" in output["error"]

    def test_hydrate_kwargs_threaded(self):
        from engines.discount_strategy.flow import DiscountStrategyEngine

        captured: dict = {}

        def _spy(*, supplied, capability_name, list_field,
                 limit=None, query=None, **_):
            captured["supplied"] = supplied
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            captured["limit"] = limit
            captured["query"] = query
            return _product_fixture(1)

        with patch(
            "engines.discount_strategy.flow.hydrate",
            side_effect=_spy,
        ):
            DiscountStrategyEngine().run({
                "data": {
                    "products": [],
                    "hydrate_limit": 80,
                    "hydrate_query": "status:active",
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"
        assert captured["limit"] == 80
        assert captured["query"] == "status:active"

    def test_supplied_products_pass_through(self):
        from engines.discount_strategy.flow import DiscountStrategyEngine

        called = {"count": 0}

        def _spy(*, supplied, **_):
            called["count"] += 1
            return supplied  # pass-through

        with patch(
            "engines.discount_strategy.flow.hydrate",
            side_effect=_spy,
        ):
            DiscountStrategyEngine().run({
                "data": {"products": _product_fixture(1)},
            })

        # hydrate is always called once; the pass-through behavior
        # is what makes supplied lists short-circuit. The shared
        # core's own pass-through path is unit-tested separately.
        assert called["count"] == 1


# ─── dynamic_pricing ──────────────────────────────────────────────


class TestDynamicPricingHydration:

    def test_hydrate_fills_empty_products(self):
        from engines.dynamic_pricing.flow import DynamicPricingEngine

        with patch(
            "engines.dynamic_pricing.flow.hydrate",
            return_value=_product_fixture(2),
        ):
            output = DynamicPricingEngine().run({
                "data": {
                    "products": [],
                    "market_signals": {},
                },
            })

        if output["status"] == "error":
            assert "At least one product" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.dynamic_pricing.flow import DynamicPricingEngine

        with patch(
            "engines.dynamic_pricing.flow.hydrate",
            return_value=[],
        ):
            output = DynamicPricingEngine().run({
                "data": {
                    "products": [],
                    "market_signals": {},
                },
            })
        assert output["status"] == "error"
        assert "At least one product" in output["error"]

    def test_non_list_products_coerced_to_empty_then_hydrated(self):
        from engines.dynamic_pricing.flow import DynamicPricingEngine

        captured: dict = {}

        def _spy(*, supplied, **_):
            captured["supplied"] = supplied
            return _product_fixture(1)

        with patch(
            "engines.dynamic_pricing.flow.hydrate",
            side_effect=_spy,
        ):
            DynamicPricingEngine().run({
                "data": {
                    "products": "garbage",  # not a list
                    "market_signals": {},
                },
            })

        # Garbage input coerced to empty list before hydrate.
        assert captured["supplied"] == []

    def test_hydrate_kwargs_threaded(self):
        from engines.dynamic_pricing.flow import DynamicPricingEngine

        captured: dict = {}

        def _spy(*, capability_name, limit=None, query=None, **_):
            captured["capability_name"] = capability_name
            captured["limit"] = limit
            captured["query"] = query
            return _product_fixture(1)

        with patch(
            "engines.dynamic_pricing.flow.hydrate",
            side_effect=_spy,
        ):
            DynamicPricingEngine().run({
                "data": {
                    "products": [],
                    "market_signals": {},
                    "hydrate_limit": 50,
                    "hydrate_query": "tag:hot",
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["limit"] == 50
        assert captured["query"] == "tag:hot"


# ─── customer_segmentation ────────────────────────────────────────


class TestCustomerSegmentationHydration:

    def test_hydrate_fills_empty_customers(self):
        from engines.customer_segmentation.flow import (
            CustomerSegmentationEngine,
        )

        with patch(
            "engines.customer_segmentation.flow.hydrate",
            return_value=_customer_fixture(2),
        ):
            output = CustomerSegmentationEngine().run({
                "data": {"customers": []},
            })

        if output["status"] == "error":
            assert "No customer data provided" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.customer_segmentation.flow import (
            CustomerSegmentationEngine,
        )

        with patch(
            "engines.customer_segmentation.flow.hydrate",
            return_value=[],
        ):
            output = CustomerSegmentationEngine().run({
                "data": {"customers": []},
            })
        assert output["status"] == "error"
        assert "No customer data provided" in output["error"]

    def test_hydrate_uses_customers_capability(self):
        from engines.customer_segmentation.flow import (
            CustomerSegmentationEngine,
        )

        captured: dict = {}

        def _spy(*, capability_name, list_field, limit=None,
                 query=None, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            captured["limit"] = limit
            captured["query"] = query
            return _customer_fixture(1)

        with patch(
            "engines.customer_segmentation.flow.hydrate",
            side_effect=_spy,
        ):
            CustomerSegmentationEngine().run({
                "data": {
                    "customers": [],
                    "hydrate_limit": 100,
                    "hydrate_query": "tag:vip",
                },
            })

        assert captured["capability_name"] == \
            "SHOPIFY_FETCH_CUSTOMERS"
        assert captured["list_field"] == "customers"
        assert captured["limit"] == 100
        assert captured["query"] == "tag:vip"


# ─── loyalty ──────────────────────────────────────────────────────


class TestLoyaltyHydration:

    def test_hydrates_both_customers_and_orders(self):
        from engines.loyalty.flow import LoyaltyEngine

        capabilities_seen: list[str] = []

        def _spy(*, supplied, capability_name, list_field, **_):
            capabilities_seen.append(capability_name)
            if list_field == "customers":
                return _customer_fixture(2)
            if list_field == "orders":
                return _order_fixture(2)
            return supplied

        with patch(
            "engines.loyalty.flow.hydrate",
            side_effect=_spy,
        ):
            output = LoyaltyEngine().run({
                "data": {
                    "customers": [],
                    "orders": [],
                },
            })

        # Both capabilities invoked.
        assert "SHOPIFY_FETCH_CUSTOMERS" in capabilities_seen
        assert "SHOPIFY_FETCH_ORDERS" in capabilities_seen
        # And the standard "Customer list is required" did NOT fire.
        if output["status"] == "error":
            assert "Customer list is required" not in (
                output.get("error") or ""
            )

    def test_empty_customers_falls_through_even_if_orders_present(self):
        from engines.loyalty.flow import LoyaltyEngine

        def _spy(*, list_field, **_):
            if list_field == "orders":
                return _order_fixture(1)
            return []  # customers empty

        with patch(
            "engines.loyalty.flow.hydrate",
            side_effect=_spy,
        ):
            output = LoyaltyEngine().run({
                "data": {"customers": [], "orders": []},
            })

        assert output["status"] == "error"
        assert "Customer list is required" in output["error"]

    def test_hydrate_kwargs_shared_between_customers_and_orders(self):
        from engines.loyalty.flow import LoyaltyEngine

        seen_limits: list = []
        seen_queries: list = []

        def _spy(*, list_field, limit=None, query=None, **_):
            seen_limits.append(limit)
            seen_queries.append(query)
            if list_field == "customers":
                return _customer_fixture(1)
            return _order_fixture(1)

        with patch(
            "engines.loyalty.flow.hydrate",
            side_effect=_spy,
        ):
            LoyaltyEngine().run({
                "data": {
                    "customers": [],
                    "orders": [],
                    "hydrate_limit": 30,
                    "hydrate_query": "tag:loyalty-member",
                },
            })

        # Both calls saw the same kwargs.
        assert seen_limits == [30, 30]
        assert seen_queries == [
            "tag:loyalty-member",
            "tag:loyalty-member",
        ]


# ─── inventory ────────────────────────────────────────────────────


class TestInventoryHydration:

    def test_hydrate_fills_empty_products(self):
        from engines.inventory.flow import InventoryEngine

        injected = [
            {
                "id": f"gid://shopify/Product/{i}",
                "title": f"SKU{i}",
                "stock": 100,
                "daily_sales": 5,
                "lead_time_days": 7,
                "cost_per_unit": 10.0,
            }
            for i in range(1, 3)
        ]

        with patch(
            "engines.inventory.flow.hydrate",
            return_value=injected,
        ):
            output = InventoryEngine().run({
                "data": {"products": []},
            })

        if output["status"] == "error":
            assert "Product list is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.inventory.flow import InventoryEngine

        with patch(
            "engines.inventory.flow.hydrate",
            return_value=[],
        ):
            output = InventoryEngine().run({
                "data": {"products": []},
            })
        assert output["status"] == "error"
        assert "Product list is required" in output["error"]

    def test_hydrate_uses_list_products_capability(self):
        from engines.inventory.flow import InventoryEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, limit=None,
                 query=None, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            captured["limit"] = limit
            captured["query"] = query
            return [
                {"id": "gid://shopify/Product/1", "title": "X",
                 "stock": 50, "daily_sales": 2,
                 "lead_time_days": 5, "cost_per_unit": 1.0},
            ]

        with patch(
            "engines.inventory.flow.hydrate",
            side_effect=_spy,
        ):
            InventoryEngine().run({
                "data": {
                    "products": [],
                    "hydrate_limit": 25,
                    "hydrate_query": "inventory_total:<10",
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"
        assert captured["limit"] == 25
        assert captured["query"] == "inventory_total:<10"

    def test_non_list_products_coerced_before_hydrate(self):
        from engines.inventory.flow import InventoryEngine

        captured: dict = {}

        def _spy(*, supplied, **_):
            captured["supplied"] = supplied
            return []

        with patch(
            "engines.inventory.flow.hydrate",
            side_effect=_spy,
        ):
            InventoryEngine().run({
                "data": {"products": "not-a-list"},
            })

        assert captured["supplied"] == []
