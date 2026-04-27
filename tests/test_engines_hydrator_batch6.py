"""Tests for batch-6 of engines wired to the shared Shopify hydrator.

Five mixed-shape engines now consume
``engines._shopify_hydrator.hydrate`` to auto-fetch customers and/or
orders when callers leave the inputs empty:

  - audience_targeting           (customers gated; orders aux)
  - ltv_cac_dashboard            (customers OR orders gated)
  - kpi_tracking                 (orders OR customers gated)
  - international_expansion      (products gated; target_markets aux)
  - customer_behavior_simulator  (customers gated)

This batch is heterogeneous (different gated lists across engines),
so the parametrized harness from batch3-5 isn't a clean fit. Each
engine gets its own focused test class.
"""
from __future__ import annotations

from unittest.mock import patch


# ─── Shared fixtures ──────────────────────────────────────────────


def _customer_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/Customer/{i}",
            "total_orders": i,
            "total_spent": 100.0 * i,
            "last_purchase": "2025-01-01",
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


def _product_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/Product/{i}",
            "title": f"P{i}",
            "price": 10.0 + i,
        }
        for i in range(1, n + 1)
    ]


# ─── audience_targeting ──────────────────────────────────────────


class TestAudienceTargetingHydration:

    def test_hydrate_fills_empty_customers_and_orders(self):
        from engines.audience_targeting.flow import (
            AudienceTargetingEngine,
        )

        capabilities_seen: list[str] = []

        def _spy(*, capability_name, list_field, **_):
            capabilities_seen.append(capability_name)
            if list_field == "customers":
                return _customer_fixture(2)
            return _order_fixture(2)

        with patch(
            "engines.audience_targeting.flow.hydrate",
            side_effect=_spy,
        ):
            output = AudienceTargetingEngine().run({
                "data": {"customers": [], "orders": []},
            })

        assert "SHOPIFY_FETCH_CUSTOMERS" in capabilities_seen
        assert "SHOPIFY_FETCH_ORDERS" in capabilities_seen
        if output["status"] == "error":
            assert "Customer list is required" not in (
                output.get("error") or ""
            )

    def test_empty_customers_falls_through(self):
        from engines.audience_targeting.flow import (
            AudienceTargetingEngine,
        )

        # Both hydrate calls return []. Customer-gated guard fires.
        with patch(
            "engines.audience_targeting.flow.hydrate",
            return_value=[],
        ):
            output = AudienceTargetingEngine().run({
                "data": {"customers": [], "orders": []},
            })
        assert output["status"] == "error"
        assert "Customer list is required" in output["error"]

    def test_hydrate_kwargs_shared_between_calls(self):
        from engines.audience_targeting.flow import (
            AudienceTargetingEngine,
        )

        seen_limits: list = []
        seen_queries: list = []

        def _spy(*, list_field, limit=None, query=None, **_):
            seen_limits.append(limit)
            seen_queries.append(query)
            if list_field == "customers":
                return _customer_fixture(1)
            return _order_fixture(1)

        with patch(
            "engines.audience_targeting.flow.hydrate",
            side_effect=_spy,
        ):
            AudienceTargetingEngine().run({
                "data": {
                    "customers": [],
                    "orders": [],
                    "hydrate_limit": 90,
                    "hydrate_query": "tag:ad-target",
                },
            })

        assert seen_limits == [90, 90]
        assert seen_queries == ["tag:ad-target", "tag:ad-target"]


# ─── ltv_cac_dashboard ───────────────────────────────────────────


class TestLtvCacDashboardHydration:

    def test_hydrate_fills_either_customers_or_orders(self):
        from engines.ltv_cac_dashboard.flow import (
            LtvCacDashboardEngine,
        )

        # Caller passes neither; hydrate fills customers.
        def _spy(*, list_field, **_):
            if list_field == "customers":
                return _customer_fixture(2)
            return []  # orders empty

        with patch(
            "engines.ltv_cac_dashboard.flow.hydrate",
            side_effect=_spy,
        ):
            output = LtvCacDashboardEngine().run({
                "data": {"customers": [], "orders": []},
            })

        # OR-guard satisfied because customers got filled.
        if output["status"] == "error":
            assert "Customers or orders list is required" not in (
                output.get("error") or ""
            )

    def test_both_empty_after_hydrate_falls_through(self):
        from engines.ltv_cac_dashboard.flow import (
            LtvCacDashboardEngine,
        )

        with patch(
            "engines.ltv_cac_dashboard.flow.hydrate",
            return_value=[],
        ):
            output = LtvCacDashboardEngine().run({
                "data": {"customers": [], "orders": []},
            })

        assert output["status"] == "error"
        assert "Customers or orders list is required" \
            in output["error"]

    def test_hydrate_calls_both_capabilities(self):
        from engines.ltv_cac_dashboard.flow import (
            LtvCacDashboardEngine,
        )

        capabilities_seen: list[str] = []

        def _spy(*, capability_name, **_):
            capabilities_seen.append(capability_name)
            return _customer_fixture(1)

        with patch(
            "engines.ltv_cac_dashboard.flow.hydrate",
            side_effect=_spy,
        ):
            LtvCacDashboardEngine().run({
                "data": {"customers": [], "orders": []},
            })

        assert "SHOPIFY_FETCH_CUSTOMERS" in capabilities_seen
        assert "SHOPIFY_FETCH_ORDERS" in capabilities_seen


# ─── kpi_tracking ────────────────────────────────────────────────


class TestKpiTrackingHydration:

    def test_hydrate_fills_either_orders_or_customers(self):
        from engines.kpi_tracking.flow import KpiTrackingEngine

        def _spy(*, list_field, **_):
            if list_field == "orders":
                return _order_fixture(2)
            return []  # customers empty

        with patch(
            "engines.kpi_tracking.flow.hydrate",
            side_effect=_spy,
        ):
            output = KpiTrackingEngine().run({
                "data": {"orders": [], "customers": []},
            })

        if output["status"] == "error":
            assert "Orders or customers data is required" not in (
                output.get("error") or ""
            )

    def test_both_empty_after_hydrate_falls_through(self):
        from engines.kpi_tracking.flow import KpiTrackingEngine

        with patch(
            "engines.kpi_tracking.flow.hydrate",
            return_value=[],
        ):
            output = KpiTrackingEngine().run({
                "data": {"orders": [], "customers": []},
            })

        assert output["status"] == "error"
        assert "Orders or customers data is required" in output["error"]

    def test_hydrate_calls_both_capabilities(self):
        from engines.kpi_tracking.flow import KpiTrackingEngine

        capabilities_seen: list[str] = []

        def _spy(*, capability_name, list_field, **_):
            capabilities_seen.append(capability_name)
            if list_field == "orders":
                return _order_fixture(1)
            return _customer_fixture(1)

        with patch(
            "engines.kpi_tracking.flow.hydrate",
            side_effect=_spy,
        ):
            KpiTrackingEngine().run({
                "data": {"orders": [], "customers": []},
            })

        assert "SHOPIFY_FETCH_ORDERS" in capabilities_seen
        assert "SHOPIFY_FETCH_CUSTOMERS" in capabilities_seen


# ─── international_expansion ────────────────────────────────────


class TestInternationalExpansionHydration:

    def test_hydrate_fills_empty_products(self):
        from engines.international_expansion.flow import (
            InternationalExpansionEngine,
        )

        with patch(
            "engines.international_expansion.flow.hydrate",
            return_value=_product_fixture(2),
        ):
            output = InternationalExpansionEngine().run({
                "data": {
                    "products": [],
                    "target_markets": [{"country": "DE"}],
                },
            })

        if output["status"] == "error":
            assert "Product list is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.international_expansion.flow import (
            InternationalExpansionEngine,
        )

        with patch(
            "engines.international_expansion.flow.hydrate",
            return_value=[],
        ):
            output = InternationalExpansionEngine().run({
                "data": {
                    "products": [],
                    "target_markets": [{"country": "DE"}],
                },
            })

        assert output["status"] == "error"
        assert "Product list is required" in output["error"]

    def test_target_markets_guard_still_fires(self):
        from engines.international_expansion.flow import (
            InternationalExpansionEngine,
        )

        # Hydrate fills products, but target_markets is still empty.
        with patch(
            "engines.international_expansion.flow.hydrate",
            return_value=_product_fixture(1),
        ):
            output = InternationalExpansionEngine().run({
                "data": {"products": [], "target_markets": []},
            })

        assert output["status"] == "error"
        assert "Target markets list is required" in output["error"]


# ─── customer_behavior_simulator ────────────────────────────────


class TestCustomerBehaviorSimulatorHydration:

    def test_hydrate_fills_empty_customers(self):
        from engines.customer_behavior_simulator.flow import (
            CustomerBehaviorSimulatorEngine,
        )

        with patch(
            "engines.customer_behavior_simulator.flow.hydrate",
            return_value=_customer_fixture(2),
        ):
            output = CustomerBehaviorSimulatorEngine().run({
                "data": {
                    "customers": [],
                    "proposed_actions": [
                        {"type": "discount", "value": 10},
                    ],
                },
            })

        if output["status"] == "error":
            assert "Customer list is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.customer_behavior_simulator.flow import (
            CustomerBehaviorSimulatorEngine,
        )

        with patch(
            "engines.customer_behavior_simulator.flow.hydrate",
            return_value=[],
        ):
            output = CustomerBehaviorSimulatorEngine().run({
                "data": {
                    "customers": [],
                    "proposed_actions": [
                        {"type": "discount", "value": 10},
                    ],
                },
            })

        assert output["status"] == "error"
        assert "Customer list is required" in output["error"]

    def test_proposed_actions_guard_still_fires(self):
        from engines.customer_behavior_simulator.flow import (
            CustomerBehaviorSimulatorEngine,
        )

        # Hydrate fills customers, but proposed_actions is empty.
        with patch(
            "engines.customer_behavior_simulator.flow.hydrate",
            return_value=_customer_fixture(1),
        ):
            output = CustomerBehaviorSimulatorEngine().run({
                "data": {"customers": [], "proposed_actions": []},
            })

        assert output["status"] == "error"
        assert "At least one proposed action is required" \
            in output["error"]
