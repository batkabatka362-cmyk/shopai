"""Shopify admin UI helpers — guard-rail tests without launching
a real browser. Validates the env-handling + URL helpers + public
API shape."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from core.adapters.browser import shopify_admin as sa


class TestIsConfigured(unittest.TestCase):
    def test_requires_all_three(self) -> None:
        with patch.dict(os.environ, {
            "SHOPAI_SHOPIFY_URL": "x.myshopify.com",
            "SHOPAI_SHOPIFY_ADMIN_EMAIL": "",
            "SHOPAI_SHOPIFY_ADMIN_PASSWORD": "",
        }, clear=False):
            self.assertFalse(sa.is_configured())
        with patch.dict(os.environ, {
            "SHOPAI_SHOPIFY_URL": "x.myshopify.com",
            "SHOPAI_SHOPIFY_ADMIN_EMAIL": "a@b",
            "SHOPAI_SHOPIFY_ADMIN_PASSWORD": "pw",
        }, clear=False):
            self.assertTrue(sa.is_configured())


class TestAdminUrl(unittest.TestCase):
    def test_builds_admin_url(self) -> None:
        with patch.dict(os.environ,
                        {"SHOPAI_SHOPIFY_URL": "ts0efe-ih.myshopify.com"},
                        clear=False):
            self.assertEqual(
                sa._admin_url("content/menus/main-menu"),
                "https://admin.shopify.com/store/ts0efe-ih/content/menus/main-menu",
            )

    def test_empty_when_shop_unset(self) -> None:
        with patch.dict(os.environ,
                        {"SHOPAI_SHOPIFY_URL": ""}, clear=False):
            self.assertEqual(sa._admin_url("x"), "")


class TestUpdateMenuEarlyReturns(unittest.TestCase):
    def test_missing_creds_returns_error(self) -> None:
        with patch.dict(os.environ, {
            "SHOPAI_SHOPIFY_URL": "x.myshopify.com",
            "SHOPAI_SHOPIFY_ADMIN_EMAIL": "",
            "SHOPAI_SHOPIFY_ADMIN_PASSWORD": "",
        }, clear=False):
            out = sa.update_menu("main", [{"title": "Home", "url": "/"}])
        self.assertEqual(out["status"], "error")
        self.assertIn("EMAIL", out["reason"])


class TestSessionCache(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = sa._SESSION_PATH
        sa._SESSION_PATH = Path(self._tmp.name) / "sess.json"

    def tearDown(self) -> None:
        sa._SESSION_PATH = self._orig
        self._tmp.cleanup()

    def test_cookie_roundtrip(self) -> None:
        cookies = [{"name": "a", "value": "b", "domain": "x"}]
        sa._save_cookies(cookies)
        self.assertEqual(sa._load_cookies(), cookies)

    def test_missing_file_returns_empty_list(self) -> None:
        self.assertEqual(sa._load_cookies(), [])


if __name__ == "__main__":
    unittest.main()
