"""Peer store observer tests."""
from __future__ import annotations

import datetime as _dt
import unittest
from unittest.mock import MagicMock

from agents.research.sources import peer_store_observer as pso


def _make_response(status=200, payload=None):
    resp = MagicMock()
    resp.status_code = status
    if payload is not None:
        resp.json.return_value = payload
    return resp


def _sample_product(**overrides):
    base = {
        "id": 10001,
        "title": "Pet Slow Feeder Bowl",
        "handle": "pet-slow-feeder-bowl",
        "updated_at": "2026-04-19T00:00:00Z",
        "published_at": "2026-04-01T00:00:00Z",
        "tags": "pet, feeder, anti-gulp",
        "variants": [{"price": "29.99"}],
        "images": [
            {"src": "https://cdn.example/img.jpg"},
        ],
    }
    base.update(overrides)
    return base


class TestConstruct(unittest.TestCase):
    def test_empty_stores_available_false(self):
        src = pso.PeerStoreObserverSource([])
        self.assertFalse(src.is_available())

    def test_non_empty_available_true(self):
        src = pso.PeerStoreObserverSource(
            ["example.myshopify.com"],
        )
        self.assertTrue(src.is_available())

    def test_bad_limit_raises(self):
        with self.assertRaises(ValueError):
            pso.PeerStoreObserverSource(
                ["s.com"], per_store_limit=0,
            )

    def test_bad_timeout_raises(self):
        with self.assertRaises(ValueError):
            pso.PeerStoreObserverSource(
                ["s.com"], timeout=0,
            )

    def test_bad_retries_raises(self):
        with self.assertRaises(ValueError):
            pso.PeerStoreObserverSource(
                ["s.com"], max_retries=-1,
            )

    def test_whitespace_stores_stripped(self):
        src = pso.PeerStoreObserverSource(
            [" a.com ", "", "  ", "b.com"],
        )
        stats = src.stats()
        self.assertEqual(
            stats["stores"], ["a.com", "b.com"],
        )


class TestFetch(unittest.TestCase):
    def test_success_produces_candidates(self):
        client = MagicMock()
        client.get.return_value = _make_response(
            200, payload={
                "products": [_sample_product()],
            },
        )
        src = pso.PeerStoreObserverSource(
            ["pet.example.com"],
            backoff_base_s=0.0, http=client,
        )
        out = src.fetch()
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual(c.source, "peer:pet.example.com")
        self.assertEqual(c.title, "Pet Slow Feeder Bowl")
        self.assertAlmostEqual(c.price, 29.99)
        self.assertIn("pet", c.tags)
        self.assertTrue(c.url.endswith("pet-slow-feeder-bowl"))

    def test_per_store_limit_honored(self):
        client = MagicMock()
        client.get.return_value = _make_response(
            200, payload={
                "products": [
                    _sample_product(id=i, handle=f"p{i}")
                    for i in range(10)
                ],
            },
        )
        src = pso.PeerStoreObserverSource(
            ["s.com"], per_store_limit=3,
            backoff_base_s=0.0, http=client,
        )
        self.assertEqual(len(src.fetch(limit=100)), 3)

    def test_missing_title_skipped(self):
        client = MagicMock()
        client.get.return_value = _make_response(
            200, payload={
                "products": [
                    {"id": 1, "title": ""},
                    {"id": 2, "title": "Keep"},
                ],
            },
        )
        src = pso.PeerStoreObserverSource(
            ["s.com"], backoff_base_s=0.0, http=client,
        )
        out = src.fetch()
        self.assertEqual([c.title for c in out], ["Keep"])

    def test_bad_variants_defaults_to_zero_price(self):
        client = MagicMock()
        client.get.return_value = _make_response(
            200, payload={
                "products": [{
                    "id": 1,
                    "title": "Weird",
                    "variants": "garbage",
                }],
            },
        )
        src = pso.PeerStoreObserverSource(
            ["s.com"], backoff_base_s=0.0, http=client,
        )
        out = src.fetch()
        self.assertEqual(out[0].price, 0.0)

    def test_url_builds_from_handle(self):
        client = MagicMock()
        client.get.return_value = _make_response(
            200, payload={
                "products": [
                    _sample_product(handle="my-handle"),
                ],
            },
        )
        src = pso.PeerStoreObserverSource(
            ["shop.example.com"],
            backoff_base_s=0.0, http=client,
        )
        out = src.fetch()
        self.assertTrue(
            out[0].url.endswith("/products/my-handle"),
        )

    def test_external_id_falls_back_to_hash(self):
        client = MagicMock()
        client.get.return_value = _make_response(
            200, payload={
                "products": [
                    {
                        "title": "No ID Here",
                        "handle": "no-id",
                    },
                ],
            },
        )
        src = pso.PeerStoreObserverSource(
            ["s.com"], backoff_base_s=0.0, http=client,
        )
        out = src.fetch()
        self.assertTrue(
            out[0].external_id.startswith("peer_"),
        )

    def test_http_error_skips_store(self):
        client = MagicMock()
        client.get.return_value = _make_response(404)
        src = pso.PeerStoreObserverSource(
            ["broken.example.com"],
            backoff_base_s=0.0, http=client,
        )
        out = src.fetch()
        self.assertEqual(out, [])
        stats = src.stats()["by_store"][
            "broken.example.com"
        ]
        self.assertIn("404", stats["last_error"])

    def test_429_retried_then_surfaces(self):
        client = MagicMock()
        client.get.side_effect = [
            _make_response(429),
            _make_response(429),
        ]
        src = pso.PeerStoreObserverSource(
            ["slow.example.com"],
            max_retries=1,
            backoff_base_s=0.0, http=client,
        )
        out = src.fetch()
        self.assertEqual(out, [])
        # Called exactly max_retries + 1 times
        self.assertEqual(client.get.call_count, 2)

    def test_429_then_success(self):
        client = MagicMock()
        client.get.side_effect = [
            _make_response(429),
            _make_response(
                200, payload={
                    "products": [_sample_product()],
                },
            ),
        ]
        src = pso.PeerStoreObserverSource(
            ["s.com"],
            max_retries=1,
            backoff_base_s=0.0, http=client,
        )
        out = src.fetch()
        self.assertEqual(len(out), 1)

    def test_multi_store_one_failure_isolated(self):
        client = MagicMock()
        client.get.side_effect = [
            _make_response(
                200, payload={
                    "products": [_sample_product()],
                },
            ),
            _make_response(500),
            _make_response(
                200, payload={
                    "products": [
                        _sample_product(
                            id=2, handle="q",
                            title="Q",
                        ),
                    ],
                },
            ),
        ]
        src = pso.PeerStoreObserverSource(
            ["a.com", "b.com", "c.com"],
            max_retries=0,
            backoff_base_s=0.0,
            http=client,
        )
        out = src.fetch()
        self.assertEqual(len(out), 2)
        sources = {c.source for c in out}
        self.assertEqual(
            sources,
            {"peer:a.com", "peer:c.com"},
        )


class TestFreshnessProxy(unittest.TestCase):
    def test_no_timestamp_default(self):
        self.assertEqual(pso._freshness_proxy(None, None), 5.0)

    def test_recent_gives_high(self):
        now = _dt.datetime.now(tz=_dt.timezone.utc)
        ts = now.isoformat().replace("+00:00", "Z")
        self.assertEqual(pso._freshness_proxy(ts, None), 40.0)

    def test_old_gives_low(self):
        ts = "2020-01-01T00:00:00Z"
        self.assertEqual(pso._freshness_proxy(ts, None), 2.0)

    def test_bad_timestamp_falls_back(self):
        self.assertEqual(
            pso._freshness_proxy("not-a-date", None), 5.0,
        )


class TestStatsShape(unittest.TestCase):
    def test_stats_includes_stores(self):
        src = pso.PeerStoreObserverSource(
            ["a.com", "b.com"],
        )
        stats = src.stats()
        self.assertEqual(stats["stores"], ["a.com", "b.com"])
        self.assertIn("by_store", stats)


if __name__ == "__main__":
    unittest.main()
