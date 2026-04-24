"""Wire-up tests: SearchAgent + BrandGuard via CLI + MCP tools."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest


# ── MCP: search ─────────────────────────────────────────────


class TestSearchHandler:
    def test_missing_query_raises(self):
        from mcp_server.tools import _search_handler, ToolError
        with pytest.raises(ToolError):
            _search_handler({})
        with pytest.raises(ToolError):
            _search_handler({"query": ""})

    def test_bad_scope_raises(self):
        from mcp_server.tools import _search_handler, ToolError
        with pytest.raises(ToolError):
            _search_handler({
                "query": "x", "scope": "blogs",
            })

    def test_limit_clamped_and_floored(self):
        """Values outside 1-50 are clamped rather than
        rejected — better UX from the MCP surface."""
        from mcp_server.tools import _search_handler
        # When no router is configured + nothing registered,
        # SearchAgent returns an empty list. We care only
        # about the clamp + shape here.
        from agents.search import SearchAgent
        with patch.object(
            SearchAgent, "search", return_value=[],
        ) as fake_search:
            out = _search_handler({
                "query": "cozy lamp",
                "scope": "web",
                "limit": 9999,
            })
            assert fake_search.call_args.kwargs["limit"] == 50
            assert out["total"] == 0
            assert out["scope"] == "web"

    def test_returns_serialisable_shape(self):
        from mcp_server.tools import _search_handler
        from agents.search import SearchAgent, SearchResult
        fake = SearchResult(
            source="cj_dropshipping",
            kind="product",
            title="Mushroom Lamp",
            url="https://cj/m",
            snippet="cozy",
            price_usd=14.5,
            score=1.2,
        )
        with patch.object(
            SearchAgent, "search", return_value=[fake],
        ):
            out = _search_handler({
                "query": "mushroom",
                "scope": "products",
            })
        assert out["total"] == 1
        # Shape is JSON-serialisable end-to-end.
        json.dumps(out)
        hit = out["hits"][0]
        assert hit["source"] == "cj_dropshipping"
        assert hit["price_usd"] == 14.5
        assert hit["score"] == 1.2


# ── MCP: brand_check ────────────────────────────────────────


class TestBrandCheckHandler:
    def test_requires_text(self):
        from mcp_server.tools import (
            _brand_check_handler, ToolError,
        )
        with pytest.raises(ToolError):
            _brand_check_handler({})
        with pytest.raises(ToolError):
            _brand_check_handler({"text": ""})

    def test_bad_surface_surfaced_as_tool_error(self):
        from mcp_server.tools import (
            _brand_check_handler, ToolError,
        )
        with pytest.raises(ToolError):
            _brand_check_handler({
                "text": "hello", "surface": "unknown",
            })

    def test_metafields_must_be_list(self):
        from mcp_server.tools import (
            _brand_check_handler, ToolError,
        )
        with pytest.raises(ToolError):
            _brand_check_handler({
                "text": "hello",
                "surface": "ad_copy",
                "metafields": "oops",
            })

    def test_passes_with_neutral_defaults(self):
        from mcp_server.tools import _brand_check_handler
        out = _brand_check_handler({
            "text": "Cozy lamp for your nook.",
            "surface": "ad_copy",
        })
        assert out["passed"] is True
        assert out["errors"] == []
        # Shape is JSON-serialisable.
        json.dumps(out)

    def test_flags_hype_word_on_calm_brand(self):
        from mcp_server.tools import _brand_check_handler
        mf = [{
            "namespace": "shopai",
            "key": "brand",
            "value": json.dumps({
                "voice": "calm_cozy",
                "forbidden_words": [],
            }),
        }]
        out = _brand_check_handler({
            "text": "CRAZY deal on this lamp",
            "surface": "ad_copy",
            "metafields": mf,
        })
        assert out["passed"] is False
        # ALL-CAPS fires too but voice mismatch is the key.
        codes = [e["code"] for e in out["errors"]]
        assert "voice_mismatch" in codes


# ── CLI: shopai search ─────────────────────────────────────


class TestSearchCLI:
    def test_cli_handler_prints_hits(self):
        from cli import _cmd_search
        from agents.search import SearchAgent, SearchResult
        fake = SearchResult(
            source="serper", kind="web",
            title="Blog about cozy lamps",
            url="https://blog/x",
            snippet="2026 roundup",
            score=0.9,
        )
        buf = io.StringIO()
        with patch.object(
            SearchAgent, "search", return_value=[fake],
        ), redirect_stdout(buf):
            _cmd_search(
                query="cozy lamp",
                scope="web",
                limit=5,
                as_json=False,
            )
        out = buf.getvalue()
        assert "Blog about cozy lamps" in out
        assert "serper" in out

    def test_cli_json_mode_emits_valid_json(self):
        from cli import _cmd_search
        from agents.search import SearchAgent, SearchResult
        fake = SearchResult(
            source="cj_dropshipping", kind="product",
            title="Lamp", url="https://x",
            price_usd=9.99, score=1.1,
        )
        buf = io.StringIO()
        with patch.object(
            SearchAgent, "search", return_value=[fake],
        ), redirect_stdout(buf):
            _cmd_search(
                query="lamp", scope="products",
                limit=5, as_json=True,
            )
        payload = json.loads(buf.getvalue())
        assert isinstance(payload, list)
        assert payload[0]["source"] == "cj_dropshipping"
        assert payload[0]["price_usd"] == 9.99

    def test_cli_exits_on_empty_query(self):
        from cli import _cmd_search
        with pytest.raises(SystemExit):
            _cmd_search(
                query="",
                scope="all",
                limit=5,
                as_json=False,
            )


# ── Tool registry surfaces both ─────────────────────────────


class TestToolRegistry:
    def test_search_registered(self):
        from mcp_server.tools import build_default_registry
        reg = build_default_registry()
        names = {t.name for t in reg.list_tools()}
        assert "search" in names

    def test_brand_check_registered(self):
        from mcp_server.tools import build_default_registry
        reg = build_default_registry()
        names = {t.name for t in reg.list_tools()}
        assert "brand_check" in names

    def test_search_schema_requires_query(self):
        from mcp_server.tools import build_default_registry
        reg = build_default_registry()
        spec = {t.name: t for t in reg.list_tools()}["search"]
        assert "query" in spec.input_schema["required"]

    def test_brand_check_schema_requires_text(self):
        from mcp_server.tools import build_default_registry
        reg = build_default_registry()
        spec = {t.name: t for t in reg.list_tools()}["brand_check"]
        assert "text" in spec.input_schema["required"]
