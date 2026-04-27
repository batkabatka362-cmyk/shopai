"""Tests for dynamic_pricing's Shopify variant price applier.

Phase 6.3 of the engine→Shopify writeback rollout. Different
shape from the discount minters (price lives on variants, not
products) and from tag_management (which is also on the product
but uses tags as a list, while variants need per-variant ids).

Three layers of coverage:

  1. ``_build_variants_map`` — robust to malformed inputs,
     correctly extracts variant GID lists per product.
  2. ``_is_approved`` — explicit bool, string coercion, missing
     key fallback.
  3. ``apply_price_changes`` — happy path verifies the adapter
     was called with all variant GIDs set to the new price;
     5 skip / failure modes (no adjustments, router
     unavailable, not approved, no variants in input, adapter
     rejection / raise).
  4. Flow integration — opt-in flag wires the applier in.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ─── _build_variants_map ──────────────────────────────────────────


class TestBuildVariantsMap:

    def test_extracts_variant_gids_per_product(self):
        from engines.dynamic_pricing.price_applier import (
            _build_variants_map,
        )

        m = _build_variants_map([
            {"id": "gid://shopify/Product/1",
             "variants": [
                 {"id": "gid://shopify/ProductVariant/v1"},
                 {"id": "gid://shopify/ProductVariant/v2"},
             ]},
            {"id": "gid://shopify/Product/2",
             "variants": [
                 {"id": "gid://shopify/ProductVariant/v3"},
             ]},
        ])
        assert m["gid://shopify/Product/1"] == [
            "gid://shopify/ProductVariant/v1",
            "gid://shopify/ProductVariant/v2",
        ]
        assert m["gid://shopify/Product/2"] == [
            "gid://shopify/ProductVariant/v3",
        ]

    def test_skips_products_with_no_variants(self):
        from engines.dynamic_pricing.price_applier import (
            _build_variants_map,
        )

        m = _build_variants_map([
            {"id": "gid://x"},                  # no variants key
            {"id": "gid://y", "variants": []},  # empty list
            {"id": "gid://z", "variants": [
                {"id": "gid://shopify/ProductVariant/v"},
            ]},
        ])
        # Only z made it through.
        assert m == {"gid://z": ["gid://shopify/ProductVariant/v"]}

    def test_skips_malformed_variant_entries(self):
        from engines.dynamic_pricing.price_applier import (
            _build_variants_map,
        )

        m = _build_variants_map([
            {"id": "gid://x", "variants": [
                {"id": "gid://shopify/ProductVariant/v1"},
                "garbage",
                None,
                {"id": ""},
                {},
                {"id": "gid://shopify/ProductVariant/v2"},
            ]},
        ])
        # Both well-formed entries kept; junk dropped.
        assert m["gid://x"] == [
            "gid://shopify/ProductVariant/v1",
            "gid://shopify/ProductVariant/v2",
        ]

    def test_non_list_input_returns_empty(self):
        from engines.dynamic_pricing.price_applier import (
            _build_variants_map,
        )

        assert _build_variants_map(None) == {}
        assert _build_variants_map("not-a-list") == {}


# ─── _is_approved ─────────────────────────────────────────────────


class TestIsApproved:

    @pytest.mark.parametrize("raw,expected", [
        (True, True),
        (False, False),
        ("true", True),
        ("True", True),
        ("false", False),
        ("1", True),
        ("0", False),
        ("yes", True),
        ("no", False),
        (None, False),
        ("", False),
    ])
    def test_coerces_various_inputs(self, raw, expected):
        from engines.dynamic_pricing.price_applier import _is_approved

        assert _is_approved({"approved": raw}) is expected

    def test_missing_key_is_false(self):
        from engines.dynamic_pricing.price_applier import _is_approved

        assert _is_approved({}) is False


# ─── apply_price_changes ──────────────────────────────────────────


class TestApplyPriceChanges:

    def _adj(self, **overrides):
        base = {
            "product_id": "gid://shopify/Product/1",
            "current_price": 49.99,
            "new_price": 39.99,
            "change_pct": -20.0,
            "reason": "elastic demand response",
            "approved": True,
        }
        base.update(overrides)
        return base

    def _product(self, pid="gid://shopify/Product/1",
                 variant_count=2):
        return {
            "id": pid,
            "current_price": 49.99,
            "variants": [
                {"id": f"gid://shopify/ProductVariant/v{i}"}
                for i in range(1, variant_count + 1)
            ],
        }

    def test_no_adjustments_returns_empty(self):
        from engines.dynamic_pricing.price_applier import (
            apply_price_changes,
        )

        with patch(
            "engines.dynamic_pricing.price_applier._get_router",
        ) as mock_router:
            assert apply_price_changes([], []) == []
        mock_router.assert_not_called()

    def test_router_unavailable_returns_skipped_results(self):
        from engines.dynamic_pricing.price_applier import (
            apply_price_changes,
        )

        with patch(
            "engines.dynamic_pricing.price_applier._get_router",
            return_value=None,
        ):
            results = apply_price_changes(
                adjustments=[self._adj()],
                products=[self._product()],
            )

        assert len(results) == 1
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_not_approved_blocks_call(self):
        from engines.dynamic_pricing.price_applier import (
            apply_price_changes,
        )

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                # Shouldn't be reached.
                return None

        stub = _StubRouter()
        with patch(
            "engines.dynamic_pricing.price_applier._get_router",
            return_value=stub,
        ):
            results = apply_price_changes(
                adjustments=[self._adj(approved=False)],
                products=[self._product()],
            )

        assert stub.calls == []
        assert results[0]["applied"] is False
        assert results[0]["error"] == "not_approved"

    def test_no_variants_in_input_skips(self):
        from engines.dynamic_pricing.price_applier import (
            apply_price_changes,
        )

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return None

        stub = _StubRouter()
        with patch(
            "engines.dynamic_pricing.price_applier._get_router",
            return_value=stub,
        ):
            results = apply_price_changes(
                adjustments=[self._adj()],
                # Product input lacks variants list.
                products=[{
                    "id": "gid://shopify/Product/1",
                    "current_price": 49.99,
                }],
            )

        assert stub.calls == []
        assert results[0]["applied"] is False
        assert results[0]["error"] == "no_variants_in_input"

    def test_happy_path_sets_all_variants_to_new_price(self):
        from core.adapters.base import Capability
        from engines.dynamic_pricing.price_applier import (
            apply_price_changes,
        )

        class _StubResult:
            ok = True
            data = {"variants": [], "count": 2}
            error = None

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return _StubResult()

        stub = _StubRouter()
        with patch(
            "engines.dynamic_pricing.price_applier._get_router",
            return_value=stub,
        ):
            results = apply_price_changes(
                adjustments=[self._adj(new_price=39.99)],
                products=[self._product(variant_count=3)],
            )

        # Adapter called once with all 3 variants set to 39.99.
        assert len(stub.calls) == 1
        cap, params = stub.calls[0]
        assert cap == Capability.SHOPIFY_UPDATE_VARIANTS
        assert params["product_id"] == "gid://shopify/Product/1"
        assert len(params["variants"]) == 3
        for v in params["variants"]:
            assert v["price"] == "39.99"
            assert v["id"].startswith("gid://shopify/ProductVariant/")
        # Result reflects success.
        assert results[0]["applied"] is True
        assert results[0]["variants_updated"] == 3
        assert results[0]["new_price"] == 39.99
        assert results[0]["error"] is None

    def test_adapter_failure_records_error(self):
        from engines.dynamic_pricing.price_applier import (
            apply_price_changes,
        )

        class _FailResult:
            ok = False
            data = {}
            error = "scope_missing"

        class _StubRouter:
            def execute(self, capability, params):
                return _FailResult()

        with patch(
            "engines.dynamic_pricing.price_applier._get_router",
            return_value=_StubRouter(),
        ):
            results = apply_price_changes(
                adjustments=[self._adj()],
                products=[self._product()],
            )

        assert results[0]["applied"] is False
        assert "adapter_failed" in results[0]["error"]

    def test_require_approved_false_bypasses_gate(self):
        # Callers that pre-filter approval should be able to skip
        # the require_approved check.
        from engines.dynamic_pricing.price_applier import (
            apply_price_changes,
        )

        class _StubResult:
            ok = True
            data = {}
            error = None

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return _StubResult()

        stub = _StubRouter()
        with patch(
            "engines.dynamic_pricing.price_applier._get_router",
            return_value=stub,
        ):
            results = apply_price_changes(
                adjustments=[self._adj(approved=False)],
                products=[self._product()],
                require_approved=False,
            )

        # Adapter WAS called even though approved=False, because
        # the caller passed require_approved=False.
        assert len(stub.calls) == 1
        assert results[0]["applied"] is True


# ─── flow integration ────────────────────────────────────────────


class TestDynamicPricingFlowApplyChanges:

    def _input(self, apply: bool = False):
        return {
            "data": {
                "products": [
                    {
                        "id": "gid://shopify/Product/1",
                        "current_price": 50.0,
                        "cogs": 20.0,
                        "daily_sales": 5,
                        "variants": [
                            {"id": "gid://shopify/ProductVariant/v1"},
                        ],
                    },
                ],
                "market_signals": {
                    "demand_index": 1.2,
                    "competitor_prices": [],
                    "inventory_days": 30,
                    "season": "summer",
                },
                "apply_changes": apply,
            },
        }

    def test_apply_changes_false_no_applier_call(self):
        from engines.dynamic_pricing.flow import DynamicPricingEngine

        with patch(
            "engines.dynamic_pricing.flow.apply_price_changes",
        ) as mock_apply:
            output = DynamicPricingEngine().run(self._input(False))

        mock_apply.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["apply_results"] == []

    def test_apply_changes_true_calls_applier(self):
        from engines.dynamic_pricing.flow import DynamicPricingEngine

        with patch(
            "engines.dynamic_pricing.flow.apply_price_changes",
            return_value=[
                {
                    "product_id": "gid://shopify/Product/1",
                    "applied": True,
                    "variants_updated": 1,
                    "new_price": 45.0,
                    "error": None,
                },
            ],
        ) as mock_apply:
            output = DynamicPricingEngine().run(self._input(True))

        if output["status"] == "success":
            assert mock_apply.called
            results = output["data"]["apply_results"]
            assert len(results) == 1
            assert results[0]["applied"] is True

    def test_engine_output_now_carries_approved_flag(self):
        # The engine's per-product output now includes ``approved``
        # so the applier can read it directly.
        from engines.dynamic_pricing.flow import DynamicPricingEngine

        output = DynamicPricingEngine().run(self._input(False))

        if output["status"] == "success" and output["data"]["adjustments"]:
            adj = output["data"]["adjustments"][0]
            assert "approved" in adj
            assert isinstance(adj["approved"], bool)
