"""Unit tests for core.adapters.browser.alibaba.

Playwright itself is stubbed — we test the parsing helpers and the
chromium-executable discovery path without standing up a real browser.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from core.adapters.browser import alibaba


class TestParsePrice(unittest.TestCase):
    def test_dollar_sign_with_space(self) -> None:
        self.assertEqual(alibaba._parse_price("$ 12.99"), 12.99)

    def test_us_prefix_range(self) -> None:
        self.assertEqual(alibaba._parse_price("US$4.50-6.20"), 4.5)

    def test_comma_thousand_separator(self) -> None:
        self.assertEqual(alibaba._parse_price("US$1,299.00"), 1299.0)

    def test_integer_price(self) -> None:
        self.assertEqual(alibaba._parse_price("Price: 10"), 10.0)

    def test_empty_returns_zero(self) -> None:
        self.assertEqual(alibaba._parse_price(""), 0.0)
        self.assertEqual(alibaba._parse_price("ask for quote"), 0.0)


class TestChromiumDiscovery(unittest.TestCase):
    def test_explicit_executable_wins(self) -> None:
        with patch.dict(
            os.environ,
            {"PLAYWRIGHT_CHROMIUM_EXECUTABLE": __file__},  # any existing file
        ):
            self.assertEqual(alibaba._chromium_executable(), __file__)

    def test_missing_everything_returns_none(self) -> None:
        with patch.dict(os.environ, {
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE": "",
            "PLAYWRIGHT_BROWSERS_PATH": "/nonexistent",
        }):
            with patch("os.path.isfile", return_value=False):
                self.assertIsNone(alibaba._chromium_executable())


class TestScrapeSafety(unittest.TestCase):
    def test_scrape_rejects_non_http_url(self) -> None:
        self.assertEqual(alibaba.scrape(""), {})
        self.assertEqual(alibaba.scrape("ftp://foo"), {})
        self.assertEqual(alibaba.scrape("not-a-url"), {})

    def test_scrape_handles_playwright_missing(self) -> None:
        # If playwright import fails the scraper should return {} not crash
        with patch.dict(
            "sys.modules",
            {"playwright": None, "playwright.sync_api": None},
        ):
            result = alibaba.scrape("https://www.alibaba.com/product/fake.html")
        # May not actually fail because playwright IS installed in test env;
        # the point is no exception escapes.
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
