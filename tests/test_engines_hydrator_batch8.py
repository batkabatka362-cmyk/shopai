"""Tests for batch-8 of engines wired to the shared Shopify hydrator.

This batch consists primarily of auxiliary hydration — the gated
input is something not directly representable in Shopify, but a
secondary input (products / orders / customers) IS. Hydrating that
secondary input enriches the pipeline without changing the gate.

  - supplier         orders aux       (suppliers gated)
  - wishlist         products+customers aux (wishlists gated)
  - warranty         products as one side of an OR-gate (claims is the other)
  - customer_journey customers aux    (events gated)
  - demand_analysis  products aux     (market_data gated)

Heterogeneous batch — each engine gets a focused test class.
"""
from __future__ import annotations

from unittest.mock import patch


# ─── Shared fixtures ──────────────────────────────────────────────


def _product_fixture(n: int = 2) -> list[dict]:
    return [
        {"id": f"gid://shopify/Product/{i}", "title": f"P{i}",
         "price": 10.0 + i, "warranty_term_months": 12}
        for i in range(1, n + 1)
    ]


def _order_fixture(n: int = 2) -> list[dict]:
    return [
        {"id": f"gid://shopify/Order/{i}",
         "supplier_id": f"sup-{i}",
         "total": 50.0,
         "delivery_status": "delivered",
         "lead_time_days": 5}
        for i in range(1, n + 1)
    ]


def _customer_fixture(n: int = 2) -> list[dict]:
    return [
        {"id": f"gid://shopify/Customer/{i}",
         "total_orders": i, "total_spent": 100.0 * i}
        for i in range(1, n + 1)
    ]


# ─── supplier (orders auxiliary, suppliers gated) ────────────────


class TestSupplierHydration:

    def test_hydrate_invoked_for_orders(self):
        from engines.supplier.flow import SupplierEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _order_fixture(2)

        with patch(
            "engines.supplier.flow.hydrate",
            side_effect=_spy,
        ):
            SupplierEngine().run({
                "data": {
                    "suppliers": [{"id": "sup-1", "name": "S1"}],
                    "orders": [],
                },
            })

        assert captured["capability_name"] == "SHOPIFY_FETCH_ORDERS"
        assert captured["list_field"] == "orders"

    def test_suppliers_guard_still_fires(self):
        # Hydrate fills orders, but suppliers is empty → gate fires.
        from engines.supplier.flow import SupplierEngine

        with patch(
            "engines.supplier.flow.hydrate",
            return_value=_order_fixture(1),
        ):
            output = SupplierEngine().run({
                "data": {"suppliers": [], "orders": []},
            })

        assert output["status"] == "error"
        assert "Suppliers list is required" in output["error"]


# ─── wishlist (products+customers aux, wishlists gated) ──────────


class TestWishlistHydration:

    def test_hydrate_invoked_for_both_products_and_customers(self):
        from engines.wishlist.flow import WishlistEngine

        capabilities_seen: list[str] = []

        def _spy(*, capability_name, list_field, **_):
            capabilities_seen.append(capability_name)
            if list_field == "products":
                return _product_fixture(1)
            return _customer_fixture(1)

        with patch(
            "engines.wishlist.flow.hydrate",
            side_effect=_spy,
        ):
            WishlistEngine().run({
                "data": {
                    "wishlists": [{"id": "wl-1"}],
                    "products": [],
                    "customers": [],
                },
            })

        assert "SHOPIFY_LIST_PRODUCTS" in capabilities_seen
        assert "SHOPIFY_FETCH_CUSTOMERS" in capabilities_seen

    def test_wishlists_guard_still_fires(self):
        from engines.wishlist.flow import WishlistEngine

        with patch(
            "engines.wishlist.flow.hydrate",
            return_value=_product_fixture(1),
        ):
            output = WishlistEngine().run({
                "data": {"wishlists": [], "products": [], "customers": []},
            })

        assert output["status"] == "error"
        assert "Wishlists list is required" in output["error"]


# ─── warranty (products as one OR-gate side) ─────────────────────


class TestWarrantyHydration:

    def test_hydrate_fills_empty_products(self):
        from engines.warranty.flow import WarrantyEngine

        with patch(
            "engines.warranty.flow.hydrate",
            return_value=_product_fixture(2),
        ):
            output = WarrantyEngine().run({
                "data": {"products": [], "claims": []},
            })

        # Hydrated products → "Products or claims required" must NOT
        # be the failure reason.
        if output["status"] == "error":
            assert "Products or claims required" not in (
                output.get("error") or ""
            )

    def test_or_gate_falls_through_when_both_empty(self):
        from engines.warranty.flow import WarrantyEngine

        # Hydrate returns empty → both products and claims empty.
        with patch(
            "engines.warranty.flow.hydrate",
            return_value=[],
        ):
            output = WarrantyEngine().run({
                "data": {"products": [], "claims": []},
            })

        assert output["status"] == "error"
        assert "Products or claims required" in output["error"]

    def test_hydrate_uses_list_products_capability(self):
        from engines.warranty.flow import WarrantyEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _product_fixture(1)

        with patch(
            "engines.warranty.flow.hydrate",
            side_effect=_spy,
        ):
            WarrantyEngine().run({
                "data": {"products": [], "claims": []},
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"


# ─── customer_journey (customers aux, events gated) ─────────────


class TestCustomerJourneyHydration:

    def test_hydrate_invoked_for_customers(self):
        from engines.customer_journey.flow import (
            CustomerJourneyEngine,
        )

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _customer_fixture(2)

        with patch(
            "engines.customer_journey.flow.hydrate",
            side_effect=_spy,
        ):
            CustomerJourneyEngine().run({
                "data": {
                    "customers": [],
                    "events": [
                        {"customer_id": "c1", "type": "view"},
                    ],
                },
            })

        assert captured["capability_name"] == \
            "SHOPIFY_FETCH_CUSTOMERS"
        assert captured["list_field"] == "customers"

    def test_events_guard_still_fires(self):
        from engines.customer_journey.flow import (
            CustomerJourneyEngine,
        )

        with patch(
            "engines.customer_journey.flow.hydrate",
            return_value=_customer_fixture(1),
        ):
            output = CustomerJourneyEngine().run({
                "data": {"customers": [], "events": []},
            })

        assert output["status"] == "error"
        assert "Events list is required" in output["error"]


# ─── demand_analysis (products aux, market_data gated) ──────────


class TestDemandAnalysisHydration:

    def test_hydrate_invoked_for_products(self):
        from engines.demand_analysis.flow import (
            DemandAnalysisEngine,
        )

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _product_fixture(2)

        with patch(
            "engines.demand_analysis.flow.hydrate",
            side_effect=_spy,
        ):
            DemandAnalysisEngine().run({
                "data": {
                    "market_data": {"size_estimate": 1_000_000},
                    "products": [],
                },
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"

    def test_market_data_guard_still_fires(self):
        from engines.demand_analysis.flow import (
            DemandAnalysisEngine,
        )

        with patch(
            "engines.demand_analysis.flow.hydrate",
            return_value=_product_fixture(1),
        ):
            output = DemandAnalysisEngine().run({
                "data": {"market_data": {}, "products": []},
            })

        assert output["status"] == "error"
        assert "Market data is required" in output["error"]
