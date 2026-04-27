"""Tests for batch-4 of engines wired to the shared Shopify hydrator.

Five product-list engines now consume
``engines._shopify_hydrator.hydrate`` to auto-fetch products when
callers leave the input list empty:

  - marketplace            (also requires `marketplaces` config)
  - price_elasticity
  - profitability_calculator
  - product_ranking
  - product_scoring

All five share the identical product-hydration shape, so the test
suite is a parametrized harness — same pattern adopted in batch3.
The marketplace engine has a secondary `marketplaces` guard that
fires AFTER products is satisfied; the tests pass a non-empty
marketplaces list to keep the focus on the hydration behavior.
"""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest


def _product_fixture(n: int = 2) -> list[dict]:
    return [
        {
            "id": f"gid://shopify/Product/{i}",
            "title": f"P{i}",
            "price": 10.0 + i,
            "cogs": 5.0,
            "daily_sales": 1.0 + i,
            "stock": 100,
            "category": "general",
        }
        for i in range(1, n + 1)
    ]


# (module_path, engine_class_name, error_substring, extra_data)
ENGINES = [
    (
        "engines.marketplace.flow",
        "MarketplaceEngine",
        "Product list is required",
        # marketplace has a secondary `marketplaces` guard that
        # fires AFTER products. Pass a non-empty list so the test
        # only asserts on the products-hydration behavior.
        {"marketplaces": [{"id": "amazon"}]},
    ),
    (
        "engines.price_elasticity.flow",
        "PriceElasticityEngine",
        "Product list is required",
        {},
    ),
    (
        "engines.profitability_calculator.flow",
        "ProfitabilityCalculatorEngine",
        "Product list is required",
        {},
    ),
    (
        "engines.product_ranking.flow",
        "ProductRankingEngine",
        "Product list is required",
        {},
    ),
    (
        "engines.product_scoring.flow",
        "ProductScoringEngine",
        "Product list is required",
        {},
    ),
]


def _engine(module_path: str, class_name: str):
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)()


@pytest.mark.parametrize(
    "module_path,class_name,err_msg,extra_data", ENGINES,
)
class TestBatch4Hydration:

    def test_hydrate_fills_empty_products(
        self, module_path, class_name, err_msg, extra_data,
    ):
        with patch(
            f"{module_path}.hydrate",
            return_value=_product_fixture(2),
        ):
            output = _engine(module_path, class_name).run({
                "data": {"products": [], **extra_data},
            })

        # Auto-fill succeeded → "Product list is required" must NOT
        # be the failure reason.
        if output["status"] == "error":
            assert err_msg not in (output.get("error") or "")

    def test_empty_supplied_and_empty_hydrated_falls_through(
        self, module_path, class_name, err_msg, extra_data,
    ):
        with patch(
            f"{module_path}.hydrate",
            return_value=[],
        ):
            output = _engine(module_path, class_name).run({
                "data": {"products": [], **extra_data},
            })
        assert output["status"] == "error"
        assert err_msg in output["error"]

    def test_hydrate_uses_list_products_capability(
        self, module_path, class_name, err_msg, extra_data,
    ):
        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _product_fixture(1)

        with patch(f"{module_path}.hydrate", side_effect=_spy):
            _engine(module_path, class_name).run({
                "data": {"products": [], **extra_data},
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"

    def test_hydrate_kwargs_threaded(
        self, module_path, class_name, err_msg, extra_data,
    ):
        captured: dict = {}

        def _spy(*, limit=None, query=None, **_):
            captured["limit"] = limit
            captured["query"] = query
            return _product_fixture(1)

        with patch(f"{module_path}.hydrate", side_effect=_spy):
            _engine(module_path, class_name).run({
                "data": {
                    "products": [],
                    "hydrate_limit": 33,
                    "hydrate_query": "tag:b4",
                    **extra_data,
                },
            })

        assert captured["limit"] == 33
        assert captured["query"] == "tag:b4"

    def test_non_list_products_coerced_before_hydrate(
        self, module_path, class_name, err_msg, extra_data,
    ):
        captured: dict = {}

        def _spy(*, supplied, **_):
            captured["supplied"] = supplied
            return []

        with patch(f"{module_path}.hydrate", side_effect=_spy):
            _engine(module_path, class_name).run({
                "data": {"products": "not-a-list", **extra_data},
            })

        assert captured["supplied"] == []
