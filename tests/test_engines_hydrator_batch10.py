"""Tests for batch-10 of engines wired to the shared Shopify hydrator.

This batch introduces a new helper — ``hydrate_one`` — for engines
that take a single ``data.product`` / ``data.order`` (dict) rather
than a list. The helper calls the same Capability with ``limit=1``
and returns the first item or an empty dict.

Engines wired:

  - fraud_detection   gated on order (dict)    → SHOPIFY_FETCH_ORDERS
  - pricing           gated on product (dict)  → SHOPIFY_LIST_PRODUCTS
  - demand_estimator  gated on product (dict)  → SHOPIFY_LIST_PRODUCTS

Tests cover both the shared ``hydrate_one`` core and the per-engine
integrations.
"""
from __future__ import annotations

from unittest.mock import patch


# ─── Stubs ────────────────────────────────────────────────────────


class _StubResult:
    def __init__(self, *, ok, data=None, error=None):
        self.ok = ok
        self.data = data or {}
        self.error = error


class _StubRouter:
    def __init__(self, *, result):
        self.result = result
        self.calls: list[tuple] = []

    def execute(self, capability, params):
        self.calls.append((capability, params))
        return self.result


# ─── hydrate_one core ────────────────────────────────────────────


class TestHydrateOne:

    def test_supplied_passes_through(self):
        from engines._shopify_hydrator import hydrate_one

        supplied = {"id": "gid://shopify/Product/1", "title": "X"}
        with patch(
            "engines._shopify_hydrator._get_router",
        ) as mock_router:
            result = hydrate_one(
                supplied=supplied,
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
            )
        assert result is supplied
        mock_router.assert_not_called()

    def test_empty_dict_triggers_fetch(self):
        from core.adapters.base import Capability
        from engines._shopify_hydrator import hydrate_one

        stub = _StubRouter(result=_StubResult(
            ok=True,
            data={"products": [
                {"id": "gid://shopify/Product/1", "title": "First"},
                {"id": "gid://shopify/Product/2", "title": "Second"},
            ]},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_one(
                supplied={},
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
            )

        cap, params = stub.calls[0]
        assert cap == Capability.SHOPIFY_LIST_PRODUCTS
        assert params["limit"] == 1
        # Returns the FIRST item only.
        assert result["title"] == "First"

    def test_none_input_triggers_fetch(self):
        from engines._shopify_hydrator import hydrate_one

        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": [{"id": "gid://x"}]},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_one(
                supplied=None,
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
            )
        assert result == {"id": "gid://x"}

    def test_empty_response_returns_empty_dict(self):
        from engines._shopify_hydrator import hydrate_one

        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": []},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            result = hydrate_one(
                supplied={},
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
            )
        assert result == {}

    def test_router_unavailable_returns_empty_dict(self):
        from engines._shopify_hydrator import hydrate_one

        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=None,
        ):
            result = hydrate_one(
                supplied={},
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
            )
        assert result == {}

    def test_query_passed_through(self):
        from engines._shopify_hydrator import hydrate_one

        stub = _StubRouter(result=_StubResult(
            ok=True, data={"products": [{"id": "gid://x"}]},
        ))
        with patch(
            "engines._shopify_hydrator._get_router",
            return_value=stub,
        ):
            hydrate_one(
                supplied={},
                capability_name="SHOPIFY_LIST_PRODUCTS",
                list_field="products",
                query="status:active",
            )
        _, params = stub.calls[0]
        assert params["query"] == "status:active"


# ─── fraud_detection ─────────────────────────────────────────────


class TestFraudDetectionHydration:

    def test_hydrate_fills_empty_order(self):
        from engines.fraud_detection.flow import FraudDetectionEngine

        with patch(
            "engines.fraud_detection.flow.hydrate_one",
            return_value={
                "id": "gid://shopify/Order/1",
                "email": "x@y.com",
                "ip_address": "1.2.3.4",
                "customer": {"phone": "+1"},
            },
        ):
            output = FraudDetectionEngine().run({
                "data": {"order": {}},
            })

        if output["status"] == "error":
            assert "Order data is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.fraud_detection.flow import FraudDetectionEngine

        with patch(
            "engines.fraud_detection.flow.hydrate_one",
            return_value={},
        ):
            output = FraudDetectionEngine().run({
                "data": {"order": {}},
            })

        assert output["status"] == "error"
        assert "Order data is required" in output["error"]

    def test_hydrate_uses_orders_capability(self):
        from engines.fraud_detection.flow import FraudDetectionEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return {"id": "gid://x"}

        with patch(
            "engines.fraud_detection.flow.hydrate_one",
            side_effect=_spy,
        ):
            FraudDetectionEngine().run({
                "data": {"order": {}},
            })

        assert captured["capability_name"] == "SHOPIFY_FETCH_ORDERS"
        assert captured["list_field"] == "orders"


# ─── pricing ─────────────────────────────────────────────────────


class TestPricingHydration:

    def test_hydrate_fills_empty_product(self):
        from engines.pricing.flow import PricingEngine

        with patch(
            "engines.pricing.flow.hydrate_one",
            return_value={
                "id": "gid://shopify/Product/1",
                "title": "X",
                "cogs": 5.0,
            },
        ):
            output = PricingEngine().run({
                "data": {"product": {}},
            })

        if output["status"] == "error":
            assert "Product data is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.pricing.flow import PricingEngine

        with patch(
            "engines.pricing.flow.hydrate_one",
            return_value={},
        ):
            output = PricingEngine().run({
                "data": {"product": {}},
            })

        assert output["status"] == "error"
        assert "Product data is required" in output["error"]

    def test_hydrate_uses_products_capability(self):
        from engines.pricing.flow import PricingEngine

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return {"id": "gid://x"}

        with patch(
            "engines.pricing.flow.hydrate_one",
            side_effect=_spy,
        ):
            PricingEngine().run({
                "data": {"product": {}},
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"


# ─── demand_estimator ────────────────────────────────────────────


class TestDemandEstimatorHydration:

    def test_hydrate_fills_empty_product(self):
        from engines.demand_estimator.flow import (
            DemandEstimatorEngine,
        )

        with patch(
            "engines.demand_estimator.flow.hydrate_one",
            return_value={
                "id": "gid://shopify/Product/1",
                "title": "X",
                "price": 99.0,
            },
        ):
            output = DemandEstimatorEngine().run({
                "data": {"product": {}, "market_size": 1000},
            })

        if output["status"] == "error":
            assert "Product data is required" not in (
                output.get("error") or ""
            )

    def test_empty_supplied_and_empty_hydrated_falls_through(self):
        from engines.demand_estimator.flow import (
            DemandEstimatorEngine,
        )

        with patch(
            "engines.demand_estimator.flow.hydrate_one",
            return_value={},
        ):
            output = DemandEstimatorEngine().run({
                "data": {"product": {}},
            })

        assert output["status"] == "error"
        assert "Product data is required" in output["error"]

    def test_hydrate_uses_products_capability(self):
        from engines.demand_estimator.flow import (
            DemandEstimatorEngine,
        )

        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return {"id": "gid://x"}

        with patch(
            "engines.demand_estimator.flow.hydrate_one",
            side_effect=_spy,
        ):
            DemandEstimatorEngine().run({
                "data": {"product": {}},
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"
