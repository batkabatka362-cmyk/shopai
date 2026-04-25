"""Unit tests for the competitor price monitor — parsing + CRUD only.

We don't spin up Playwright here; the probe path is tested indirectly
through _parse_price_text and _delta_pct.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.autonomous import competitor_monitor as cm


class TestParsePrice(unittest.TestCase):
    def test_dollar_sign(self) -> None:
        self.assertEqual(cm._parse_price_text("Sale price: $19.99"), 19.99)

    def test_usd_prefix(self) -> None:
        self.assertEqual(cm._parse_price_text("USD$1,299.00"), 1299.0)

    def test_euro_sign(self) -> None:
        self.assertEqual(cm._parse_price_text("Now €12.50"), 12.5)

    def test_bare_decimal_fallback(self) -> None:
        self.assertEqual(cm._parse_price_text("Price 29.99 total"), 29.99)

    def test_no_match_returns_none(self) -> None:
        self.assertIsNone(cm._parse_price_text("Contact sales for quote"))
        self.assertIsNone(cm._parse_price_text(""))


class TestDeltaPct(unittest.TestCase):
    def test_price_up(self) -> None:
        self.assertAlmostEqual(cm._delta_pct(10, 12), 20.0)

    def test_price_down(self) -> None:
        self.assertAlmostEqual(cm._delta_pct(10, 8), -20.0)

    def test_no_change(self) -> None:
        self.assertEqual(cm._delta_pct(10, 10), 0.0)

    def test_missing_values(self) -> None:
        self.assertIsNone(cm._delta_pct(None, 10))
        self.assertIsNone(cm._delta_pct(10, None))
        self.assertIsNone(cm._delta_pct(0, 10))


class TestCrud(unittest.TestCase):
    def setUp(self) -> None:
        # Redirect the store to a tmp path
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = cm._STORE_PATH
        from pathlib import Path
        cm._STORE_PATH = Path(self._tmp.name) / "competitors.json"

    def tearDown(self) -> None:
        cm._STORE_PATH = self._orig
        self._tmp.cleanup()

    def test_add_url_new(self) -> None:
        self.assertTrue(cm.add_url("https://example.com/p/1"))
        self.assertEqual(len(cm.list_tracked()), 1)

    def test_add_url_duplicate_returns_false(self) -> None:
        cm.add_url("https://example.com/p/1")
        self.assertFalse(cm.add_url("https://example.com/p/1"))
        self.assertEqual(len(cm.list_tracked()), 1)

    def test_add_url_rejects_non_http(self) -> None:
        self.assertFalse(cm.add_url("ftp://example.com/p/1"))
        self.assertFalse(cm.add_url(""))
        self.assertEqual(len(cm.list_tracked()), 0)

    def test_remove_url(self) -> None:
        cm.add_url("https://example.com/p/1")
        self.assertTrue(cm.remove_url("https://example.com/p/1"))
        self.assertEqual(len(cm.list_tracked()), 0)

    def test_remove_url_not_found(self) -> None:
        self.assertFalse(cm.remove_url("https://example.com/p/999"))


if __name__ == "__main__":
    unittest.main()
