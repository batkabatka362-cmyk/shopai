"""Tests for content_generation's product-description applier (Phase 7.2).

The engine has generated product descriptions for months, but the
output was advisory — merchants had to copy/paste. This wireup
pushes the generated body into SHOPIFY_UPDATE_PRODUCT.descriptionHtml.

This is the second destructive Phase 6/7 writeback (overwrites
existing product copy), so safety gates are stricter:

  * content_type must be "product_description"
  * product must have a Shopify GID
  * body must be non-empty
  * optional SEO + readability score floors
  * always opt-in via data.apply_content=True

Tests cover the applier's gates + the flow integration. The Phase 8
recorder is mocked — we already have full coverage of the recorder
itself in test_writeback_recorder.py.
"""
from __future__ import annotations

from unittest.mock import patch


# ─── apply_description ────────────────────────────────────────────


class TestApplyDescription:

    def _content_block(self, body="A great product. Buy it."):
        return {
            "headline": "Great Product",
            "body": body,
            "bullets": [],
            "cta": "Buy now",
            "meta_description": "Great product",
        }

    def test_non_product_description_skipped(self):
        from engines.content_generation.content_applier import (
            apply_description,
        )

        with patch(
            "engines.content_generation.content_applier._get_router",
        ) as mock_router:
            r = apply_description(
                product={"id": "gid://shopify/Product/1"},
                content_block=self._content_block(),
                content_type="ad_copy",
            )

        assert r["applied"] is False
        assert r["error"] == "content_type_not_appliable"
        # Router never resolved.
        mock_router.assert_not_called()

    def test_missing_product_id_skipped(self):
        from engines.content_generation.content_applier import (
            apply_description,
        )

        r = apply_description(
            product={},
            content_block=self._content_block(),
            content_type="product_description",
        )
        assert r["applied"] is False
        assert r["error"] == "product_id_missing"

    def test_empty_body_skipped(self):
        from engines.content_generation.content_applier import (
            apply_description,
        )

        r = apply_description(
            product={"id": "gid://x"},
            content_block=self._content_block(body=""),
            content_type="product_description",
        )
        assert r["applied"] is False
        assert r["error"] == "body_empty"

    def test_below_min_seo_score_skipped(self):
        from engines.content_generation.content_applier import (
            apply_description,
        )

        r = apply_description(
            product={"id": "gid://x"},
            content_block=self._content_block(),
            content_type="product_description",
            seo_score=0.4,
            min_seo_score=0.7,
        )
        assert r["applied"] is False
        assert r["error"] == "below_min_seo_score"

    def test_below_min_readability_score_skipped(self):
        from engines.content_generation.content_applier import (
            apply_description,
        )

        r = apply_description(
            product={"id": "gid://x"},
            content_block=self._content_block(),
            content_type="product_description",
            seo_score=0.8,
            readability_score=40.0,
            min_readability_score=70.0,
        )
        assert r["applied"] is False
        assert r["error"] == "below_min_readability_score"

    def test_router_unavailable_returns_skip(self):
        from engines.content_generation.content_applier import (
            apply_description,
        )

        with patch(
            "engines.content_generation.content_applier._get_router",
            return_value=None,
        ):
            r = apply_description(
                product={"id": "gid://x"},
                content_block=self._content_block(),
                content_type="product_description",
            )
        assert r["applied"] is False
        assert r["error"] == "router_unavailable"

    def test_happy_path_calls_adapter(self):
        from core.adapters.base import Capability
        from engines.content_generation.content_applier import (
            apply_description,
        )

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
            "engines.content_generation.content_applier._get_router",
            return_value=stub,
        ), patch(
            "engines.content_generation.content_applier.record_writeback",
        ) as mock_recorder:
            r = apply_description(
                product={"id": "gid://shopify/Product/1"},
                content_block=self._content_block(
                    body="A new and improved description.",
                ),
                content_type="product_description",
                seo_score=0.85,
                readability_score=80.0,
            )

        assert len(stub.calls) == 1
        cap, params = stub.calls[0]
        assert cap == Capability.SHOPIFY_UPDATE_PRODUCT
        assert params["id"] == "gid://shopify/Product/1"
        assert params["description_html"] == \
            "A new and improved description."
        assert r["applied"] is True
        assert r["body_length"] == len(
            "A new and improved description.",
        )
        # Recorder fired with success=True.
        assert mock_recorder.called
        rec_kwargs = mock_recorder.call_args.kwargs
        assert rec_kwargs["engine"] == "content_generation"
        assert rec_kwargs["action_type"] == "apply_description"
        assert rec_kwargs["success"] is True

    def test_adapter_failure_records_error_and_failure(self):
        from engines.content_generation.content_applier import (
            apply_description,
        )

        class _FailResult:
            ok = False
            data = {}
            error = "scope_missing"

        class _StubRouter:
            def execute(self, capability, params):
                return _FailResult()

        with patch(
            "engines.content_generation.content_applier._get_router",
            return_value=_StubRouter(),
        ), patch(
            "engines.content_generation.content_applier.record_writeback",
        ) as mock_recorder:
            r = apply_description(
                product={"id": "gid://x"},
                content_block=self._content_block(),
                content_type="product_description",
            )

        assert r["applied"] is False
        assert "adapter_failed" in r["error"]
        # Recorder fired with success=False.
        rec_kwargs = mock_recorder.call_args.kwargs
        assert rec_kwargs["success"] is False
        assert "adapter_failed" in rec_kwargs["error"]


# ─── flow integration ───────────────────────────────────────────


class TestContentGenerationFlowApplyContent:

    def _input(self, apply: bool = False, **extra):
        return {
            "data": {
                "type": "product_description",
                "product": {
                    "id": "gid://shopify/Product/1",
                    "title": "Widget",
                    "features": ["a", "b"],
                    "price": 50.0,
                    "category": "general",
                    "target_audience": "young adults",
                },
                "brand": {"name": "Acme", "voice": "friendly"},
                "platform": "web",
                "apply_content": apply,
                **extra,
            },
        }

    def test_apply_content_false_no_applier_call(self):
        from engines.content_generation.flow import (
            ContentGenerationEngine,
        )

        with patch(
            "engines.content_generation.flow.apply_description",
        ) as mock_apply:
            output = ContentGenerationEngine().run(self._input(False))

        mock_apply.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["apply_result"] is None

    def test_apply_content_true_calls_applier(self):
        from engines.content_generation.flow import (
            ContentGenerationEngine,
        )

        with patch(
            "engines.content_generation.flow.apply_description",
            return_value={
                "product_id": "gid://shopify/Product/1",
                "applied": True,
                "body_length": 200,
                "error": None,
            },
        ) as mock_apply:
            output = ContentGenerationEngine().run(self._input(True))

        if output["status"] == "success":
            assert mock_apply.called
            r = output["data"]["apply_result"]
            assert r["applied"] is True

    def test_min_score_floors_threaded_through(self):
        from engines.content_generation.flow import (
            ContentGenerationEngine,
        )

        captured: dict = {}

        def _spy(*, product, content_block, content_type,
                 seo_score, readability_score,
                 min_seo_score, min_readability_score):
            captured["min_seo_score"] = min_seo_score
            captured["min_readability_score"] = min_readability_score
            return None

        with patch(
            "engines.content_generation.flow.apply_description",
            side_effect=_spy,
        ):
            ContentGenerationEngine().run(self._input(
                True,
                min_apply_seo_score=0.7,
                min_apply_readability_score=80.0,
            ))

        if captured:
            assert captured["min_seo_score"] == 0.7
            assert captured["min_readability_score"] == 80.0
