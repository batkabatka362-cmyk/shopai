"""Tests for batch-5 of engines wired to the shared Shopify hydrator.

Five more product-list engines now consume
``engines._shopify_hydrator.hydrate`` to auto-fetch products when
callers leave the input list empty:

  - shipping_optimization  (error: "At least one product is required")
  - search_optimization    (error: "Products list is required")
  - tag_management         (error: "Products list is required")
  - stock_prediction       (error: "Product list is required")
  - wholesale_b2b          (error: "Product list is required")

Same parametrized harness as batch3 / batch4 — error substring is
parameter-driven so the slight wording variations across engines
don't bloat the test count.
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
            "weight_kg": 0.5,
            "stock": 100,
            "category": "general",
        }
        for i in range(1, n + 1)
    ]


# (module_path, engine_class_name, error_substring)
ENGINES = [
    (
        "engines.shipping_optimization.flow",
        "ShippingOptimizationEngine",
        "At least one product is required",
    ),
    (
        "engines.search_optimization.flow",
        "SearchOptimizationEngine",
        "Products list is required",
    ),
    (
        "engines.tag_management.flow",
        "TagManagementEngine",
        "Products list is required",
    ),
    (
        "engines.stock_prediction.flow",
        "StockPredictionEngine",
        "Product list is required",
    ),
    (
        "engines.wholesale_b2b.flow",
        "WholesaleB2bEngine",
        "Product list is required",
    ),
]


def _engine(module_path: str, class_name: str):
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)()


@pytest.mark.parametrize("module_path,class_name,err_msg", ENGINES)
class TestBatch5Hydration:

    def test_hydrate_fills_empty_products(
        self, module_path, class_name, err_msg,
    ):
        with patch(
            f"{module_path}.hydrate",
            return_value=_product_fixture(2),
        ):
            output = _engine(module_path, class_name).run({
                "data": {"products": []},
            })

        # Auto-fill succeeded → guard message must NOT be the
        # failure reason.
        if output["status"] == "error":
            assert err_msg not in (output.get("error") or "")

    def test_empty_supplied_and_empty_hydrated_falls_through(
        self, module_path, class_name, err_msg,
    ):
        with patch(
            f"{module_path}.hydrate",
            return_value=[],
        ):
            output = _engine(module_path, class_name).run({
                "data": {"products": []},
            })
        assert output["status"] == "error"
        assert err_msg in output["error"]

    def test_hydrate_uses_list_products_capability(
        self, module_path, class_name, err_msg,
    ):
        captured: dict = {}

        def _spy(*, capability_name, list_field, **_):
            captured["capability_name"] = capability_name
            captured["list_field"] = list_field
            return _product_fixture(1)

        with patch(f"{module_path}.hydrate", side_effect=_spy):
            _engine(module_path, class_name).run({
                "data": {"products": []},
            })

        assert captured["capability_name"] == "SHOPIFY_LIST_PRODUCTS"
        assert captured["list_field"] == "products"

    def test_hydrate_kwargs_threaded(
        self, module_path, class_name, err_msg,
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
                    "hydrate_limit": 17,
                    "hydrate_query": "tag:b5",
                },
            })

        assert captured["limit"] == 17
        assert captured["query"] == "tag:b5"

    def test_non_list_products_coerced_before_hydrate(
        self, module_path, class_name, err_msg,
    ):
        captured: dict = {}

        def _spy(*, supplied, **_):
            captured["supplied"] = supplied
            return []

        with patch(f"{module_path}.hydrate", side_effect=_spy):
            _engine(module_path, class_name).run({
                "data": {"products": "not-a-list"},
            })

        assert captured["supplied"] == []
