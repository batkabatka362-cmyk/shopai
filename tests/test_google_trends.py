"""Tests for core.adapters.trends.google_trends."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.adapters.trends.google_trends import (
    GoogleTrendsAdapter,
    TrendingSearch,
)


def _payload(items: list[dict]) -> str:
    body = {
        "default": {
            "trendingSearchesDays": [
                {"date": "20260420", "trendingSearches": items},
            ],
        },
    }
    return ")]}',\n" + json.dumps(body)


def _http_response(status=200, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


def _item(query: str, *, traffic="10K+", related=None):
    return {
        "title": {"query": query},
        "formattedTraffic": traffic,
        "relatedQueries": [
            {"query": q} for q in (related or [])
        ],
    }


class TestConfig(unittest.TestCase):
    def test_negative_ttl_raises(self):
        with self.assertRaises(ValueError):
            GoogleTrendsAdapter(cache_ttl_s=-1)

    def test_is_available(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            ad = GoogleTrendsAdapter(
                db_path=Path(tmp.name) / "t.db",
            )
            self.assertTrue(ad.is_available())
            ad.close()
        finally:
            tmp.cleanup()


class TestFetch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.client = MagicMock()
        self.adapter = GoogleTrendsAdapter(
            db_path=Path(self._tmp.name) / "t.db",
            http=self.client,
        )

    def tearDown(self):
        self.adapter.close()
        self._tmp.cleanup()

    def test_parses_keywords(self):
        self.client.get.return_value = _http_response(
            200,
            text=_payload([
                _item("pet feeder", related=["slow feeder"]),
                _item("kitchen gadget"),
            ]),
        )
        out = self.adapter.top_searches(geo="US")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].keyword, "pet feeder")
        self.assertEqual(out[0].geo, "US")
        self.assertEqual(out[0].traffic, "10K+")
        self.assertIn("slow feeder", out[0].related_queries)

    def test_respects_limit(self):
        self.client.get.return_value = _http_response(
            200,
            text=_payload([
                _item(f"kw{i}") for i in range(10)
            ]),
        )
        out = self.adapter.top_searches(geo="US", limit=3)
        self.assertEqual(len(out), 3)

    def test_strips_json_prefix(self):
        # Must tolerate the ')]}\',' prefix; ensure no decode error
        self.client.get.return_value = _http_response(
            200,
            text=")]}',\n" + json.dumps({
                "default": {
                    "trendingSearchesDays": [
                        {"trendingSearches": [
                            _item("x"),
                        ]},
                    ],
                },
            }),
        )
        out = self.adapter.top_searches(geo="US")
        self.assertEqual(len(out), 1)

    def test_http_error_returns_empty(self):
        self.client.get.return_value = _http_response(
            500, text="boom",
        )
        out = self.adapter.top_searches(geo="US")
        self.assertEqual(out, [])
        self.assertIn("500", self.adapter.stats()["last_error"])

    def test_malformed_json_returns_empty(self):
        self.client.get.return_value = _http_response(
            200, text=")]}',\nnot json",
        )
        out = self.adapter.top_searches(geo="US")
        self.assertEqual(out, [])
        self.assertIn(
            "json decode", self.adapter.stats()["last_error"],
        )

    def test_missing_title_skipped(self):
        self.client.get.return_value = _http_response(
            200,
            text=_payload([
                {"title": {}},   # no query
                _item("real one"),
            ]),
        )
        out = self.adapter.top_searches(geo="US")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].keyword, "real one")


class TestGeos(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.client = MagicMock()
        self.adapter = GoogleTrendsAdapter(
            db_path=Path(self._tmp.name) / "t.db",
            http=self.client,
        )

    def tearDown(self):
        self.adapter.close()
        self._tmp.cleanup()

    def test_invalid_geo_returns_empty(self):
        out = self.adapter.top_searches(geo="ZZ")
        self.assertEqual(out, [])
        self.assertIn(
            "unsupported geo",
            self.adapter.stats()["last_error"],
        )

    def test_eu_aggregates_proxy_geos(self):
        def _by_geo(url, params=None, **kw):
            geo = (params or {}).get("geo", "")
            return _http_response(
                200,
                text=_payload([_item(f"trend_{geo}")]),
            )

        self.client.get.side_effect = _by_geo
        out = self.adapter.top_searches(geo="EU", limit=10)
        # At least 3 unique proxy geos should show up
        keys = {t.keyword for t in out}
        self.assertIn("trend_GB", keys)
        self.assertIn("trend_DE", keys)
        self.assertIn("trend_FR", keys)

    def test_eu_dedupes_identical_keywords(self):
        # Every proxy returns the same keyword
        self.client.get.return_value = _http_response(
            200, text=_payload([_item("same_kw")]),
        )
        out = self.adapter.top_searches(geo="EU", limit=10)
        self.assertEqual(len(out), 1)


class TestCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.client = MagicMock()
        self.now = [1_000_000.0]
        self.adapter = GoogleTrendsAdapter(
            db_path=Path(self._tmp.name) / "t.db",
            http=self.client,
            cache_ttl_s=3600.0,
            now_fn=lambda: self.now[0],
        )

    def tearDown(self):
        self.adapter.close()
        self._tmp.cleanup()

    def test_cache_hit_skips_http(self):
        self.client.get.return_value = _http_response(
            200, text=_payload([_item("x")]),
        )
        self.adapter.top_searches(geo="US")
        self.adapter.top_searches(geo="US")
        self.assertEqual(self.client.get.call_count, 1)

    def test_cache_expiry_refetches(self):
        self.client.get.return_value = _http_response(
            200, text=_payload([_item("x")]),
        )
        self.adapter.top_searches(geo="US")
        # Jump past TTL
        self.now[0] += 3601.0
        self.adapter.top_searches(geo="US")
        self.assertEqual(self.client.get.call_count, 2)

    def test_use_cache_false_bypasses(self):
        self.client.get.return_value = _http_response(
            200, text=_payload([_item("x")]),
        )
        self.adapter.top_searches(geo="US")
        self.adapter.top_searches(geo="US", use_cache=False)
        self.assertEqual(self.client.get.call_count, 2)


class TestStats(unittest.TestCase):
    def test_stats_shape(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            client = MagicMock()
            client.get.return_value = _http_response(
                200, text=_payload([_item("a")]),
            )
            ad = GoogleTrendsAdapter(
                db_path=Path(tmp.name) / "t.db",
                http=client,
            )
            ad.top_searches(geo="US")
            s = ad.stats()
            self.assertEqual(s["adapter"], "google_trends")
            self.assertEqual(s["last_fetch_count"], 1)
            self.assertEqual(s["last_error"], "")
            self.assertEqual(len(s["cache_entries"]), 1)
            self.assertEqual(
                s["cache_entries"][0]["geo"], "US",
            )
            ad.close()
        finally:
            tmp.cleanup()


class TestDict(unittest.TestCase):
    def test_trending_search_as_dict(self):
        t = TrendingSearch(
            keyword="pet feeder",
            geo="US",
            traffic="10K+",
            related_queries=("slow feeder",),
            fetched_at=123.0,
        )
        d = t.as_dict()
        self.assertEqual(d["keyword"], "pet feeder")
        self.assertEqual(d["related_queries"], ["slow feeder"])


if __name__ == "__main__":
    unittest.main()
