"""Tests for tag_management's Shopify product-tag applier.

Phase 6.4 of the engine→Shopify writeback rollout. Different
shape from the discount-code minters because tags don't live on
their own resource — they're a field on the product. The applier
calls ``SHOPIFY_UPDATE_PRODUCT`` with a merged tag list (existing
+ new, dedup case-insensitive) per assignment.

Three layers of coverage:

  1. ``_merge_tags`` helper — parametric dedup logic.
  2. ``_build_existing_tags_map`` — robust to malformed inputs.
  3. ``apply_tags`` — happy path, router unavailable, adapter
     failure, no-new-tags short-circuit, missing product_id.
  4. Flow integration — opt-in flag wires the applier in cleanly.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ─── _merge_tags ───────────────────────────────────────────────────


class TestMergeTags:

    def test_appends_new_tags_to_existing(self):
        from engines.tag_management.tag_applier import _merge_tags

        merged, added = _merge_tags(
            existing=["sale", "summer"],
            new=["bestseller"],
        )
        assert merged == ["sale", "summer", "bestseller"]
        assert added == 1

    def test_dedup_is_case_insensitive(self):
        from engines.tag_management.tag_applier import _merge_tags

        merged, added = _merge_tags(
            existing=["Sale", "Summer"],
            new=["sale", "BESTSELLER"],
        )
        # "sale" already exists (case-insensitive); only
        # "BESTSELLER" is new.
        assert added == 1
        assert "BESTSELLER" in merged

    def test_no_new_tags_returns_zero_added(self):
        from engines.tag_management.tag_applier import _merge_tags

        merged, added = _merge_tags(
            existing=["sale", "summer"],
            new=["sale", "Summer"],  # all already present
        )
        assert added == 0
        assert merged == ["sale", "summer"]

    def test_strips_blank_and_non_string(self):
        from engines.tag_management.tag_applier import _merge_tags

        merged, added = _merge_tags(
            existing=["sale", "  ", "summer"],
            new=[None, "", "  ", "fall", 123, "fall"],
        )
        assert added == 1
        assert "fall" in merged
        # Non-string + blank entries dropped.
        assert "  " not in merged
        assert None not in merged

    def test_empty_existing(self):
        from engines.tag_management.tag_applier import _merge_tags

        merged, added = _merge_tags(
            existing=[],
            new=["a", "b", "c"],
        )
        assert merged == ["a", "b", "c"]
        assert added == 3


# ─── _build_existing_tags_map ─────────────────────────────────────


class TestBuildExistingTagsMap:

    def test_extracts_per_product_tag_lists(self):
        from engines.tag_management.tag_applier import (
            _build_existing_tags_map,
        )

        m = _build_existing_tags_map([
            {"id": "gid://shopify/Product/1", "tags": ["a", "b"]},
            {"id": "gid://shopify/Product/2", "tags": ["c"]},
        ])
        assert m["gid://shopify/Product/1"] == ["a", "b"]
        assert m["gid://shopify/Product/2"] == ["c"]

    def test_handles_comma_separated_string(self):
        # Defensive: some upstreams ship comma-separated tag strings.
        from engines.tag_management.tag_applier import (
            _build_existing_tags_map,
        )

        m = _build_existing_tags_map([
            {"id": "gid://shopify/Product/1", "tags": "a, b , c"},
        ])
        assert m["gid://shopify/Product/1"] == ["a", "b", "c"]

    def test_skips_malformed_entries(self):
        from engines.tag_management.tag_applier import (
            _build_existing_tags_map,
        )

        m = _build_existing_tags_map([
            {"id": "", "tags": ["x"]},        # blank id
            None,                              # not a dict
            "garbage",                         # not a dict
            {"id": "gid://x", "tags": ["a"]},
        ])
        assert m == {"gid://x": ["a"]}

    def test_non_list_input_returns_empty_map(self):
        from engines.tag_management.tag_applier import (
            _build_existing_tags_map,
        )

        assert _build_existing_tags_map(None) == {}
        assert _build_existing_tags_map("not-a-list") == {}


# ─── apply_tags ────────────────────────────────────────────────────


class TestApplyTags:

    def test_no_assignments_returns_empty(self):
        from engines.tag_management.tag_applier import apply_tags

        with patch(
            "engines.tag_management.tag_applier._get_router",
        ) as mock_router:
            assert apply_tags([], []) == []
        mock_router.assert_not_called()

    def test_router_unavailable_returns_skipped_results(self):
        from engines.tag_management.tag_applier import apply_tags

        with patch(
            "engines.tag_management.tag_applier._get_router",
            return_value=None,
        ):
            results = apply_tags(
                assignments=[
                    {"product_id": "gid://x", "tags": ["new"]},
                ],
                products=[{"id": "gid://x", "tags": ["old"]}],
            )

        assert len(results) == 1
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_no_new_tags_short_circuits(self):
        # All assignment tags already exist on the product →
        # don't call the adapter at all.
        from engines.tag_management.tag_applier import apply_tags

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
            "engines.tag_management.tag_applier._get_router",
            return_value=stub,
        ):
            results = apply_tags(
                assignments=[
                    {"product_id": "gid://x",
                     "tags": ["existing"]},  # already present
                ],
                products=[
                    {"id": "gid://x", "tags": ["existing"]},
                ],
            )

        assert len(stub.calls) == 0
        assert results[0]["applied"] is False
        assert results[0]["error"] == "no_new_tags"
        assert results[0]["tags_added"] == 0

    def test_happy_path_calls_adapter_with_merged_tags(self):
        from core.adapters.base import Capability
        from engines.tag_management.tag_applier import apply_tags

        class _StubResult:
            ok = True
            data = {"product": {}}
            error = None

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return _StubResult()

        stub = _StubRouter()
        with patch(
            "engines.tag_management.tag_applier._get_router",
            return_value=stub,
        ):
            results = apply_tags(
                assignments=[
                    {"product_id": "gid://x",
                     "tags": ["new1", "new2"]},
                ],
                products=[
                    {"id": "gid://x", "tags": ["existing"]},
                ],
            )

        # Adapter called once with the merged tag list.
        assert len(stub.calls) == 1
        cap, params = stub.calls[0]
        assert cap == Capability.SHOPIFY_UPDATE_PRODUCT
        assert params["id"] == "gid://x"
        assert set(params["tags"]) == {"existing", "new1", "new2"}
        # Result reflects success.
        assert results[0]["applied"] is True
        assert results[0]["tags_added"] == 2
        assert results[0]["error"] is None

    def test_adapter_failure_records_error(self):
        from engines.tag_management.tag_applier import apply_tags

        class _FailResult:
            ok = False
            data = {}
            error = "scope_missing"

        class _StubRouter:
            def execute(self, capability, params):
                return _FailResult()

        with patch(
            "engines.tag_management.tag_applier._get_router",
            return_value=_StubRouter(),
        ):
            results = apply_tags(
                assignments=[
                    {"product_id": "gid://x", "tags": ["new"]},
                ],
                products=[{"id": "gid://x", "tags": []}],
            )

        assert results[0]["applied"] is False
        assert "adapter_failed" in results[0]["error"]

    def test_adapter_raise_records_error(self):
        from engines.tag_management.tag_applier import apply_tags

        class _ExplodingRouter:
            def execute(self, capability, params):
                raise RuntimeError("network_down")

        with patch(
            "engines.tag_management.tag_applier._get_router",
            return_value=_ExplodingRouter(),
        ):
            results = apply_tags(
                assignments=[
                    {"product_id": "gid://x", "tags": ["new"]},
                ],
                products=[{"id": "gid://x", "tags": []}],
            )

        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── flow integration ────────────────────────────────────────────


class TestTagManagementFlowApplyTags:

    def _input(self, apply: bool = False, **extra):
        return {
            "data": {
                "products": [
                    {"id": "gid://shopify/Product/1",
                     "title": "Widget",
                     "tags": ["existing"],
                     "vendor": "ACME",
                     "product_type": "general",
                     "price": 10.0,
                     "description": "test"},
                ],
                "existing_tags": ["existing"],
                "apply_tags": apply,
                **extra,
            },
        }

    def test_apply_tags_false_no_applier_call(self):
        from engines.tag_management.flow import TagManagementEngine

        with patch(
            "engines.tag_management.flow.apply_tags",
        ) as mock_apply:
            output = TagManagementEngine().run(self._input(False))

        mock_apply.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["apply_results"] == []

    def test_apply_tags_true_calls_applier(self):
        from engines.tag_management.flow import TagManagementEngine

        with patch(
            "engines.tag_management.flow.apply_tags",
            return_value=[
                {"product_id": "gid://shopify/Product/1",
                 "applied": True, "tags_added": 1,
                 "merged_tags": ["existing", "auto-1"],
                 "error": None},
            ],
        ) as mock_apply:
            output = TagManagementEngine().run(self._input(True))

        if output["status"] == "success":
            assert mock_apply.called
            results = output["data"]["apply_results"]
            assert len(results) == 1
            assert results[0]["applied"] is True
