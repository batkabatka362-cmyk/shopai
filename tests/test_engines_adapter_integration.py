"""Integration tests: engine → hydrator → router → adapter.

These tests exercise the *full* call path that engine-side
hydrators rely on: the engine calls ``hydrate()``, which looks up
the router singleton, which routes to the right adapter, which
hits its (mocked) GraphQL boundary.

This layer was missing — the existing 199 hydrator-batch tests
patch ``hydrate()`` directly (verifying engines call it correctly
but skipping the routing path). The 6000+ adapter tests patch
``_gql`` directly (verifying GraphQL handling but skipping the
engine integration). Neither catches a capability-name parity
break: an engine referencing a name no adapter claims fails
silently because the hydrator's exception path returns ``[]``.

The ``SHOPIFY_FETCH_ORDERS`` bug (PR #40) was exactly this:
14+ engines called the ``FETCH_`` form, but the orders adapter
only declared ``LIST_ORDERS``. All 199 hydrator unit tests still
passed because the hydrator was patched. All 6000+ adapter tests
still passed because they targeted the (correctly-functioning)
LIST capability. Only an integration test that runs the engine
against the real router catches this.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def configured_router(monkeypatch):
    """Boot the Shopify adapter registry with mock credentials and
    return the resulting SmartRouter."""
    from core.adapters.router import reset_router, get_router
    from core.adapters.shopify.bootstrap import register_all

    # Force-reset the singleton so adapters re-register cleanly.
    reset_router()

    # Boot all Shopify adapters with explicit mock credentials so
    # ``is_configured()`` returns True and the router accepts them
    # as candidates.
    register_all(
        shop_url="test-shop.myshopify.com",
        access_token="shpat_TEST_TOKEN",
    )

    yield get_router()

    # Clean up so other tests aren't polluted by our overrides.
    reset_router()


@pytest.fixture
def stub_orders_gql():
    """Patch the orders adapter's ``_gql`` to return canned data.

    Yields the patcher so tests can assert ``_gql`` was called
    (proving the engine→router→adapter path was exercised).
    """
    canned_orders_response = {
        "orders": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "edges": [
                {"node": {
                    "id": "gid://shopify/Order/1001",
                    "name": "#1001",
                    "tags": ["vip"],
                    "currencyCode": "USD",
                    "totalPriceSet": {
                        "shopMoney": {
                            "amount": "100.00",
                            "currencyCode": "USD",
                        },
                    },
                    "customer": {
                        "id": "gid://shopify/Customer/2001",
                        "email": "vip@example.com",
                        "numberOfOrders": 5,
                    },
                }},
            ],
        },
    }
    with patch(
        "core.adapters.shopify.orders.ShopifyOrdersAdapter._gql",
        return_value=canned_orders_response,
    ) as mock_gql:
        yield mock_gql


@pytest.fixture
def stub_customers_gql():
    """Patch the customers adapter's ``_gql`` to return canned data."""
    canned_customers_response = {
        "customers": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "edges": [
                {"node": {
                    "id": "gid://shopify/Customer/2001",
                    "email": "vip@example.com",
                    "firstName": "Vee",
                    "lastName": "Eye-Pee",
                    "numberOfOrders": 5,
                    "amountSpent": {
                        "amount": "500.00",
                        "currencyCode": "USD",
                    },
                }},
            ],
        },
    }
    with patch(
        "core.adapters.shopify.customers.ShopifyCustomersAdapter._gql",
        return_value=canned_customers_response,
    ) as mock_gql:
        yield mock_gql


# ─── Loyalty engine — full path through both FETCH_ORDERS + FETCH_CUSTOMERS ──


class TestLoyaltyEngineIntegration:
    """Loyalty engine uses both SHOPIFY_FETCH_CUSTOMERS and
    SHOPIFY_FETCH_ORDERS via the hydrator. This test verifies the
    end-to-end path actually reaches both adapters."""

    def test_hydrator_reaches_orders_and_customers_adapters(
        self,
        configured_router,
        stub_orders_gql,
        stub_customers_gql,
    ):
        from engines.loyalty.flow import LoyaltyEngine

        # Engine called with NO supplied data.customers and NO
        # data.orders. Hydrator MUST fetch both via the router
        # for the engine to run past its "Customer list is
        # required" guard.
        output = LoyaltyEngine().run({
            "data": {
                "customers": [],
                "orders": [],
            },
        })

        # The smoking-gun assertion: BOTH adapters' _gql was hit.
        # Pre-PR-#40 this would have failed for orders — the
        # SmartRouter had no route for SHOPIFY_FETCH_ORDERS, so
        # the hydrator returned [] without ever reaching the
        # adapter.
        assert stub_customers_gql.called, (
            "Customers adapter never reached — "
            "engine→hydrator→router→adapter path is broken "
            "for SHOPIFY_FETCH_CUSTOMERS"
        )
        assert stub_orders_gql.called, (
            "Orders adapter never reached — "
            "engine→hydrator→router→adapter path is broken "
            "for SHOPIFY_FETCH_ORDERS (this is the exact bug "
            "PR #40 fixed; this test prevents regression)"
        )

        # Engine ran past the input guard since hydration
        # succeeded. Downstream stages may still error on the
        # canned-but-skinny test data — what matters is that
        # "Customer list is required" is NOT the error.
        if output.get("status") == "error":
            err = output.get("error") or ""
            assert "Customer list is required" not in err
            assert "Customers list is required" not in err

    def test_when_caller_supplies_data_no_adapter_call_is_made(
        self,
        configured_router,
        stub_orders_gql,
        stub_customers_gql,
    ):
        from engines.loyalty.flow import LoyaltyEngine

        # When the caller pre-fetches, the hydrator's pass-through
        # short-circuits before any router call.
        LoyaltyEngine().run({
            "data": {
                "customers": [
                    {"id": "gid://shopify/Customer/c1",
                     "total_orders": 3, "total_spent": 200.0},
                ],
                "orders": [
                    {"id": "gid://shopify/Order/o1",
                     "customer_id": "gid://shopify/Customer/c1",
                     "total": 50.0},
                ],
            },
        })

        # Neither adapter should have been hit.
        assert not stub_customers_gql.called
        assert not stub_orders_gql.called


# ─── Discount-strategy engine — single capability (FETCH_PRODUCTS via list) ──


class TestDiscountStrategyEngineIntegration:
    """Discount-strategy engine uses SHOPIFY_LIST_PRODUCTS via the
    hydrator. Lighter test — single capability — but still
    exercises the full router path."""

    def test_hydrator_reaches_products_adapter(
        self, configured_router,
    ):
        from engines.discount_strategy.flow import DiscountStrategyEngine

        canned_products_response = {
            "products": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "edges": [
                    {"node": {
                        "id": "gid://shopify/Product/p1",
                        "title": "Test Product",
                        "handle": "test-product",
                        "status": "ACTIVE",
                        "tags": [],
                        "vendor": "ACME",
                        "productType": "general",
                        "totalInventory": 10,
                        "variants": {
                            "edges": [{"node": {
                                "id": "gid://shopify/ProductVariant/v1",
                                "price": "29.99",
                                "compareAtPrice": None,
                                "inventoryQuantity": 10,
                                "sku": "SKU-1",
                            }}],
                        },
                    }},
                ],
            },
        }

        with patch(
            "core.adapters.shopify.products.ShopifyProductsAdapter._gql",
            return_value=canned_products_response,
        ) as mock_gql:
            output = DiscountStrategyEngine().run({
                "data": {"products": []},
            })

        assert mock_gql.called, (
            "Products adapter never reached — "
            "engine→hydrator→router→adapter path is broken "
            "for SHOPIFY_LIST_PRODUCTS"
        )

        if output.get("status") == "error":
            err = output.get("error") or ""
            assert "Products list is required" not in err
