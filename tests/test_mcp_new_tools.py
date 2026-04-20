"""Tests for new MCP tools: moby_win_rate, fal_budget_status, oauth_status."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from mcp_server.tools import (
    ToolCall,
    build_default_registry,
)


class TestMobyWinRateTool(unittest.TestCase):
    def test_registered(self):
        reg = build_default_registry()
        names = {spec.name for spec in reg.list_tools()}
        self.assertIn("moby_win_rate", names)

    def test_empty_before_any_disagreements(self):
        reg = build_default_registry()
        res = reg.call(ToolCall(tool="moby_win_rate"))
        self.assertTrue(res.ok)
        self.assertIsInstance(res.content, dict)
        self.assertIn("total_resolved", res.content)


class TestFalBudgetTool(unittest.TestCase):
    def test_registered(self):
        reg = build_default_registry()
        names = {spec.name for spec in reg.list_tools()}
        self.assertIn("fal_budget_status", names)

    def test_default_no_sku(self):
        # Point the router at a temp db so we don't pollute real state
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".db",
        )
        tmp.close()
        from core.adapters.fal import video_router as vr

        class _TempRouter(vr.FalVideoRouter):
            def __init__(self, **kwargs):
                super().__init__(
                    db_path=tmp.name, **kwargs,
                )
        with patch.object(vr, "FalVideoRouter", _TempRouter):
            reg = build_default_registry()
            res = reg.call(ToolCall(tool="fal_budget_status"))
        self.assertTrue(res.ok)
        self.assertIn("configured", res.content)
        self.assertIn("weekly_cap_usd", res.content)
        self.assertNotIn("sku", res.content)

    def test_with_sku(self):
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".db",
        )
        tmp.close()
        from core.adapters.fal import video_router as vr

        class _TempRouter(vr.FalVideoRouter):
            def __init__(self, **kwargs):
                super().__init__(
                    db_path=tmp.name, **kwargs,
                )
        with patch.object(vr, "FalVideoRouter", _TempRouter):
            reg = build_default_registry()
            res = reg.call(ToolCall(
                tool="fal_budget_status",
                arguments={"sku": "sku-1"},
            ))
        self.assertTrue(res.ok)
        self.assertEqual(res.content.get("sku"), "sku-1")
        self.assertIn(
            "sku_spent_this_week_usd", res.content,
        )


class TestOAuthStatusTool(unittest.TestCase):
    def test_registered(self):
        reg = build_default_registry()
        names = {spec.name for spec in reg.list_tools()}
        self.assertIn("oauth_status", names)

    def test_status_structure(self):
        orig = {
            k: os.environ.get(k) for k in (
                "SHOPAI_SHOPIFY_URL",
                "SHOPAI_SHOPIFY_KEY",
                "SHOPAI_SHOPIFY_CLIENT_ID",
                "SHOPAI_SHOPIFY_CLIENT_SECRET",
            )
        }
        # Clear to a known-unconfigured state
        for k in orig:
            os.environ.pop(k, None)
        try:
            from core.auth import token_resolver as tr
            tr._reset_for_tests()
            reg = build_default_registry()
            res = reg.call(ToolCall(tool="oauth_status"))
        finally:
            for k, v in orig.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            tr._reset_for_tests()
        self.assertTrue(res.ok)
        self.assertIn("oauth_configured", res.content)
        self.assertIn("source", res.content)
        self.assertEqual(
            res.content["source"], "none",
        )

    def test_explicit_shop_argument(self):
        orig = {
            k: os.environ.get(k) for k in (
                "SHOPAI_SHOPIFY_URL",
                "SHOPAI_SHOPIFY_KEY",
                "SHOPAI_SHOPIFY_CLIENT_ID",
                "SHOPAI_SHOPIFY_CLIENT_SECRET",
            )
        }
        for k in orig:
            os.environ.pop(k, None)
        os.environ["SHOPAI_SHOPIFY_KEY"] = "legacy"
        try:
            from core.auth import token_resolver as tr
            tr._reset_for_tests()
            reg = build_default_registry()
            res = reg.call(ToolCall(
                tool="oauth_status",
                arguments={"shop": "explicit.myshopify.com"},
            ))
        finally:
            for k, v in orig.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            tr._reset_for_tests()
        self.assertTrue(res.ok)
        self.assertEqual(
            res.content["shop"], "explicit.myshopify.com",
        )
        self.assertEqual(
            res.content["source"], "legacy_static",
        )


if __name__ == "__main__":
    unittest.main()
