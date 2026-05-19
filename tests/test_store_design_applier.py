"""Tests for ``engines.store_design.design_applier``.

The applier translates the store_design engine envelope into
two ADDITIVE Shopify theme files via
``SHOPIFY_UPSERT_THEME_FILES``:

  * ``assets/shopai-design-tokens.json`` -- structured tokens
  * ``snippets/shopai-design-recommendations.liquid`` -- snippet

Coverage:
  1. Successful apply -> two files written, record_writeback
     called with success=True.
  2. Empty / non-success envelope short-circuits without
     touching Shopify.
  3. Missing theme_id -> error envelope.
  4. Router unavailable -> error result + record_writeback
     called with success=False.
  5. Adapter rejection -> error result + recording.
  6. Adapter raise -> error result + recording.
  7. Tokens JSON has the expected schema.
  8. Snippet liquid renders palette + nav + layout +
     mobile sub-blocks as HTML comments.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engines.store_design.design_applier import (
    _build_snippet_body,
    _build_tokens_body,
    apply_design,
)


def _envelope(**data_overrides):
    data = {
        "color_palette": {
            "primary": "#000000", "accent": "#ff0000",
        },
        "navigation": {
            "primary_links": [
                {"label": "Home", "url": "/"},
                {"label": "Shop", "url": "/collections/all"},
            ],
        },
        "layout_recommendations": [
            {
                "page": "homepage",
                "recommendation": "Add hero",
                "expected_impact": "10-15%",
            },
        ],
        "mobile_optimizations": [
            {"type": "sticky_cta", "recommendation": "Pin"},
        ],
        "estimated_conversion_lift": 0.15,
    }
    data.update(data_overrides)
    return {
        "status": "success",
        "data": data,
        "meta": {"engine": "store_design"},
        "error": None,
    }


def _ok_adapter_result(filenames):
    return SimpleNamespace(
        ok=True,
        data={
            "theme_id": "gid://shopify/OnlineStoreTheme/1",
            "upserted_count": len(filenames),
            "filenames": list(filenames),
        },
        error=None,
    )


class TestSuccessfulApply:

    def test_writes_both_files(self):
        router = MagicMock()
        router.execute.return_value = _ok_adapter_result([
            "assets/shopai-design-tokens.json",
            "snippets/shopai-design-recommendations.liquid",
        ])
        with patch(
            "engines.store_design.design_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_design.design_applier."
            "record_writeback",
        ) as record_mock:
            result = apply_design(
                _envelope(),
                theme_id="gid://shopify/OnlineStoreTheme/1",
            )

        assert result["applied"] is True
        assert result["error"] is None
        assert set(result["files_written"]) == {
            "assets/shopai-design-tokens.json",
            "snippets/shopai-design-recommendations.liquid",
        }
        # Adapter was called once with both files
        router.execute.assert_called_once()
        params = router.execute.call_args.args[1]
        assert params["theme_id"] == (
            "gid://shopify/OnlineStoreTheme/1"
        )
        assert len(params["files"]) == 2
        filenames = {f["filename"] for f in params["files"]}
        assert "assets/shopai-design-tokens.json" in filenames
        # record_writeback called with success=True
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True

    def test_store_id_propagates_to_writeback(self):
        router = MagicMock()
        router.execute.return_value = _ok_adapter_result([
            "assets/shopai-design-tokens.json",
        ])
        with patch(
            "engines.store_design.design_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_design.design_applier."
            "record_writeback",
        ) as record_mock:
            apply_design(
                _envelope(),
                theme_id="gid://shopify/OnlineStoreTheme/1",
                store_id="store-a",
            )
        params = record_mock.call_args.kwargs["params"]
        assert params["store_id"] == "store-a"


class TestEnvelopeValidation:

    def test_non_dict_input_returns_error(self):
        result = apply_design(
            None, theme_id="gid://shopify/OnlineStoreTheme/1",
        )
        assert result["applied"] is False
        assert "engine_output_not_a_dict" in result["error"]

    def test_failed_status_short_circuits(self):
        env = _envelope()
        env["status"] = "fail"
        env["error"] = "Brand info is required"
        with patch(
            "engines.store_design.design_applier._get_router",
        ) as router_mock:
            result = apply_design(
                env,
                theme_id="gid://shopify/OnlineStoreTheme/1",
            )
        # Never even tried to get the router
        router_mock.assert_not_called()
        assert result["applied"] is False
        assert "Brand info is required" in result["error"]

    def test_missing_theme_id(self):
        result = apply_design(_envelope(), theme_id="")
        assert result["applied"] is False
        assert "theme_id_required" in result["error"]

    def test_non_dict_data_field(self):
        env = _envelope()
        env["data"] = "broken"
        result = apply_design(
            env, theme_id="gid://shopify/OnlineStoreTheme/1",
        )
        assert result["applied"] is False


class TestAdapterFailureModes:

    def test_router_unavailable(self):
        with patch(
            "engines.store_design.design_applier._get_router",
            return_value=None,
        ), patch(
            "engines.store_design.design_applier."
            "record_writeback",
        ) as record_mock:
            result = apply_design(
                _envelope(),
                theme_id="gid://shopify/OnlineStoreTheme/1",
            )
        assert result["applied"] is False
        assert "router_unavailable" in result["error"]
        # Writeback STILL records the failure
        assert record_mock.call_args.kwargs["success"] is False

    def test_adapter_rejection(self):
        router = MagicMock()
        router.execute.return_value = SimpleNamespace(
            ok=False, error="scope_missing: write_themes",
            data=None,
        )
        with patch(
            "engines.store_design.design_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_design.design_applier."
            "record_writeback",
        ) as record_mock:
            result = apply_design(
                _envelope(),
                theme_id="gid://shopify/OnlineStoreTheme/1",
            )
        assert result["applied"] is False
        assert "scope_missing" in result["error"]
        assert record_mock.call_args.kwargs["success"] is False

    def test_adapter_raise(self):
        router = MagicMock()
        router.execute.side_effect = RuntimeError("network")
        with patch(
            "engines.store_design.design_applier._get_router",
            return_value=router,
        ), patch(
            "engines.store_design.design_applier."
            "record_writeback",
        ) as record_mock:
            result = apply_design(
                _envelope(),
                theme_id="gid://shopify/OnlineStoreTheme/1",
            )
        assert result["applied"] is False
        assert "adapter_raise" in result["error"]
        assert record_mock.call_args.kwargs["success"] is False


class TestTokensBody:

    def test_schema_shape(self):
        env = _envelope()
        body = _build_tokens_body(env["data"])
        payload = json.loads(body)
        assert payload["schema_version"] == 1
        assert payload["color_palette"] == {
            "primary": "#000000", "accent": "#ff0000",
        }
        assert payload["estimated_conversion_lift"] == 0.15
        assert isinstance(payload["layout_recommendations"], list)
        assert isinstance(payload["mobile_optimizations"], list)

    def test_empty_data_handled(self):
        body = _build_tokens_body({})
        payload = json.loads(body)
        assert payload["color_palette"] == {}
        assert payload["navigation"] == {}
        assert payload["layout_recommendations"] == []
        assert payload["estimated_conversion_lift"] == 0.0


class TestSnippetBody:

    def test_includes_palette_comments(self):
        body = _build_snippet_body(_envelope()["data"])
        assert "color palette" in body
        assert "primary = #000000" in body
        assert "accent = #ff0000" in body

    def test_includes_nav_links(self):
        body = _build_snippet_body(_envelope()["data"])
        assert "navigation links" in body
        assert "Home -> /" in body
        assert "Shop -> /collections/all" in body

    def test_includes_layout_recommendations(self):
        body = _build_snippet_body(_envelope()["data"])
        assert "layout recommendations" in body
        assert "Add hero" in body
        assert "10-15%" in body

    def test_includes_mobile_recommendations(self):
        body = _build_snippet_body(_envelope()["data"])
        assert "mobile optimizations" in body
        assert "sticky_cta" in body

    def test_snippet_renders_as_html_comments(self):
        """The whole body is wrapped in HTML comments or
        Liquid comment blocks -- safe to include from any
        template since it can't affect rendering."""
        body = _build_snippet_body(_envelope()["data"])
        # Open + close comment markers
        assert "{%- comment -%}" in body
        assert "{%- endcomment -%}" in body
        assert (
            "<!-- shopai:design-recommendations -->" in body
        )
        assert (
            "<!-- /shopai:design-recommendations -->" in body
        )

    def test_empty_data_renders_minimal_snippet(self):
        body = _build_snippet_body({})
        # Still has the wrapper but no sub-block headers
        assert (
            "<!-- shopai:design-recommendations -->" in body
        )
        assert "color palette" not in body
        assert "navigation links" not in body
        assert "layout recommendations" not in body
