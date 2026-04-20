"""Tests for agents.research.sources.meta_ads_library."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from agents.research.sources.meta_ads_library import (
    MetaAdsLibrarySource,
)


def _http(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = payload or {}
    return r


class TestConfig(unittest.TestCase):
    def test_unavailable_without_token(self):
        src = MetaAdsLibrarySource(
            enable_override=True, token="",
        )
        self.assertFalse(src.is_available())

    def test_unavailable_without_enable(self):
        src = MetaAdsLibrarySource(
            enable_override=False, token="t",
        )
        self.assertFalse(src.is_available())

    def test_available_with_both(self):
        src = MetaAdsLibrarySource(
            enable_override=True, token="t",
        )
        self.assertTrue(src.is_available())

    def test_env_pickup(self):
        os.environ["META_AD_LIBRARY_TOKEN"] = "env_tok"
        os.environ["SHOPAI_ENABLE_META_ADS_LIBRARY"] = "1"
        try:
            src = MetaAdsLibrarySource()
            self.assertTrue(src.is_available())
        finally:
            os.environ.pop(
                "META_AD_LIBRARY_TOKEN", None,
            )
            os.environ.pop(
                "SHOPAI_ENABLE_META_ADS_LIBRARY", None,
            )


class TestFetch(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.src = MetaAdsLibrarySource(
            enable_override=True,
            token="tok",
            http=self.client,
        )

    def test_disabled_returns_empty(self):
        src = MetaAdsLibrarySource(
            enable_override=False, token="tok",
        )
        self.assertEqual(src.fetch(), [])
        self.assertIn(
            "disabled", src.stats()["last_error"],
        )

    def test_happy_path_parses_candidates(self):
        self.client.get.return_value = _http(
            200,
            payload={
                "data": [
                    {
                        "id": "ad-1",
                        "ad_snapshot_url": (
                            "https://fb.com/ads/ad-1"
                        ),
                        "ad_creative_link_titles": [
                            "Slow Pet Feeder",
                        ],
                        "ad_creative_bodies": [
                            "$24.99 Reduces eating "
                            "speed.",
                        ],
                    },
                ],
            },
        )
        out = self.src.fetch()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "Slow Pet Feeder")
        self.assertAlmostEqual(out[0].price, 24.99)
        # margin 2.5× → cost ≈ price / 2.5
        self.assertAlmostEqual(
            out[0].cost, 9.996, places=2,
        )
        self.assertEqual(
            out[0].url,
            "https://fb.com/ads/ad-1",
        )

    def test_title_falls_back_to_body_first_line(self):
        self.client.get.return_value = _http(
            200,
            payload={
                "data": [{
                    "id": "2",
                    "ad_creative_bodies": [
                        "Amazing Gadget 2026\n"
                        "Buy now!",
                    ],
                }],
            },
        )
        out = self.src.fetch()
        self.assertEqual(len(out), 1)
        self.assertEqual(
            out[0].title, "Amazing Gadget 2026",
        )

    def test_ad_without_usable_title_skipped(self):
        self.client.get.return_value = _http(
            200,
            payload={
                "data": [
                    {"id": "3"},  # no title, no body
                    {
                        "id": "4",
                        "ad_creative_link_titles": ["Real"],
                    },
                ],
            },
        )
        out = self.src.fetch()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "Real")

    def test_http_error_surfaces(self):
        self.client.get.return_value = _http(
            503, text="busy",
        )
        self.assertEqual(self.src.fetch(), [])
        self.assertIn(
            "503", self.src.stats()["last_error"],
        )

    def test_limit_honoured(self):
        self.client.get.return_value = _http(
            200,
            payload={
                "data": [
                    {
                        "id": str(i),
                        "ad_creative_link_titles": [
                            f"Item {i}",
                        ],
                    }
                    for i in range(50)
                ],
            },
        )
        out = self.src.fetch(limit=5)
        self.assertEqual(len(out), 5)

    def test_nonlist_data_returns_empty(self):
        self.client.get.return_value = _http(
            200, payload={"data": "not-a-list"},
        )
        self.assertEqual(self.src.fetch(), [])

    def test_no_price_yields_zero_price_and_cost(self):
        self.client.get.return_value = _http(
            200,
            payload={
                "data": [{
                    "id": "5",
                    "ad_creative_link_titles": ["Free"],
                }],
            },
        )
        out = self.src.fetch()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].price, 0.0)
        self.assertEqual(out[0].cost, 0.0)


class TestStatsShape(unittest.TestCase):
    def test_stats(self):
        src = MetaAdsLibrarySource(
            enable_override=True, token="t",
        )
        s = src.stats()
        self.assertTrue(s["enabled"])
        self.assertTrue(s["has_token"])
        self.assertTrue(s["experimental"])


if __name__ == "__main__":
    unittest.main()
