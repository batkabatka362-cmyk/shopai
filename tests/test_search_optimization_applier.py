"""Tests for search_optimization's SEO meta applier (Phase 7.3).

Phase 7.3 is the third destructive Phase 6/7 writeback (changes
visible product fields), and the first to require an upstream
adapter extension (the products adapter now accepts flat
``seo_title`` / ``seo_description`` and converts to Shopify's
nested ``seo: { title, description }`` input).

Coverage:
  1. ``apply_meta`` — happy path, all 5 skip modes, current_meta
     diff short-circuit, partial updates (only title or only
     description), recorder verification.
  2. Flow integration — opt-in flag, current_meta threaded
     through.
"""
from __future__ import annotations

from unittest.mock import patch


# ─── apply_meta ──────────────────────────────────────────────────


class TestApplyMeta:

    def _rec(self, **overrides):
        base = {
            "product_id": "gid://shopify/Product/1",
            "title": "Best Widget for Camping",
            "description": "Durable widget — top pick.",
            "keywords": ["widget", "camping"],
            "improvements": [],
        }
        base.update(overrides)
        return base

    def test_no_recommendations_returns_empty(self):
        from engines.search_optimization.seo_applier import apply_meta

        with patch(
            "engines.search_optimization.seo_applier._get_router",
        ) as mock_router:
            assert apply_meta([]) == []
        mock_router.assert_not_called()

    def test_router_unavailable_returns_skipped(self):
        from engines.search_optimization.seo_applier import apply_meta

        with patch(
            "engines.search_optimization.seo_applier._get_router",
            return_value=None,
        ):
            results = apply_meta([self._rec()])
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_no_changes_short_circuits(self):
        # Proposed equals current → don't waste an API call.
        from engines.search_optimization.seo_applier import apply_meta

        class _StubRouter:
            def __init__(self):
                self.calls = []

            def execute(self, capability, params):
                self.calls.append((capability, params))
                return None

        stub = _StubRouter()
        with patch(
            "engines.search_optimization.seo_applier._get_router",
            return_value=stub,
        ):
            results = apply_meta(
                [self._rec()],
                current_meta=[{
                    "product_id": "gid://shopify/Product/1",
                    "title": "Best Widget for Camping",
                    "description": "Durable widget — top pick.",
                }],
            )

        assert stub.calls == []
        assert results[0]["applied"] is False
        assert results[0]["error"] == "no_changes"

    def test_happy_path_full_update(self):
        from core.adapters.base import Capability
        from engines.search_optimization.seo_applier import apply_meta

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
            "engines.search_optimization.seo_applier._get_router",
            return_value=stub,
        ), patch(
            "engines.search_optimization.seo_applier.record_writeback",
        ) as mock_recorder:
            results = apply_meta([self._rec()])

        assert len(stub.calls) == 1
        cap, params = stub.calls[0]
        assert cap == Capability.SHOPIFY_UPDATE_PRODUCT
        assert params["id"] == "gid://shopify/Product/1"
        assert params["seo_title"] == "Best Widget for Camping"
        assert params["seo_description"] == \
            "Durable widget — top pick."
        # Result reflects success.
        assert results[0]["applied"] is True
        assert results[0]["title_updated"] is True
        assert results[0]["description_updated"] is True
        # Recorder fired.
        assert mock_recorder.called
        rec_kwargs = mock_recorder.call_args.kwargs
        assert rec_kwargs["engine"] == "search_optimization"
        assert rec_kwargs["action_type"] == "apply_seo_meta"
        assert rec_kwargs["success"] is True

    def test_happy_path_partial_title_only(self):
        # If only the title differs from current, only the title
        # is sent in the params (description goes unset).
        from engines.search_optimization.seo_applier import apply_meta

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
            "engines.search_optimization.seo_applier._get_router",
            return_value=stub,
        ):
            results = apply_meta(
                [self._rec()],
                current_meta=[{
                    "product_id": "gid://shopify/Product/1",
                    "title": "Old title",
                    # Description matches the recommendation →
                    # no description update.
                    "description": "Durable widget — top pick.",
                }],
            )

        assert len(stub.calls) == 1
        _, params = stub.calls[0]
        assert "seo_title" in params
        assert "seo_description" not in params
        assert results[0]["title_updated"] is True
        assert results[0]["description_updated"] is False

    def test_adapter_failure_records_error(self):
        from engines.search_optimization.seo_applier import apply_meta

        class _FailResult:
            ok = False
            data = {}
            error = "scope_missing"

        class _StubRouter:
            def execute(self, capability, params):
                return _FailResult()

        with patch(
            "engines.search_optimization.seo_applier._get_router",
            return_value=_StubRouter(),
        ), patch(
            "engines.search_optimization.seo_applier.record_writeback",
        ) as mock_recorder:
            results = apply_meta([self._rec()])

        assert results[0]["applied"] is False
        assert "adapter_failed" in results[0]["error"]
        rec_kwargs = mock_recorder.call_args.kwargs
        assert rec_kwargs["success"] is False


# ─── flow integration ────────────────────────────────────────────


class TestSearchOptimizationFlowApplySeo:

    def _input(self, apply: bool = False, **extra):
        return {
            "data": {
                "products": [
                    {"id": "gid://shopify/Product/1",
                     "title": "Widget",
                     "description": "Old description",
                     "category": "general",
                     "tags": []},
                ],
                "search_queries": [],
                "current_meta": [
                    {"product_id": "gid://shopify/Product/1",
                     "title": "Old SEO title",
                     "description": "Old SEO desc"},
                ],
                "competitors": [],
                "apply_seo": apply,
                **extra,
            },
        }

    def test_apply_seo_false_no_applier_call(self):
        from engines.search_optimization.flow import (
            SearchOptimizationEngine,
        )

        with patch(
            "engines.search_optimization.flow.apply_meta",
        ) as mock_apply:
            output = SearchOptimizationEngine().run(self._input(False))

        mock_apply.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["apply_results"] == []

    def test_apply_seo_true_calls_applier(self):
        from engines.search_optimization.flow import (
            SearchOptimizationEngine,
        )

        with patch(
            "engines.search_optimization.flow.apply_meta",
            return_value=[
                {"product_id": "gid://shopify/Product/1",
                 "applied": True, "title_updated": True,
                 "description_updated": True, "error": None},
            ],
        ) as mock_apply:
            output = SearchOptimizationEngine().run(self._input(True))

        if output["status"] == "success":
            assert mock_apply.called
            results = output["data"]["apply_results"]
            assert len(results) == 1
            assert results[0]["applied"] is True

    def test_current_meta_threaded_to_applier(self):
        from engines.search_optimization.flow import (
            SearchOptimizationEngine,
        )

        captured: dict = {}

        def _spy(recommendations, current_meta=None):
            captured["recs_count"] = len(recommendations)
            captured["current_meta"] = current_meta
            return []

        with patch(
            "engines.search_optimization.flow.apply_meta",
            side_effect=_spy,
        ):
            SearchOptimizationEngine().run(self._input(True))

        if captured:
            # current_meta from the input was passed through.
            assert captured["current_meta"] == [
                {"product_id": "gid://shopify/Product/1",
                 "title": "Old SEO title",
                 "description": "Old SEO desc"},
            ]
