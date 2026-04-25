"""Webhook dedup tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.system import webhook_dedup as wd


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.d = wd.WebhookDedup(Path(self._tmp.name) / "w.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_call_unseen(self) -> None:
        v = self.d.register("shopify", {"order_id": 1})
        self.assertFalse(v.seen)
        self.assertTrue(v.digest)

    def test_second_call_seen(self) -> None:
        self.d.register("shopify", {"order_id": 1})
        v = self.d.register("shopify", {"order_id": 1})
        self.assertTrue(v.seen)

    def test_different_payloads_distinct(self) -> None:
        v1 = self.d.register("shopify", {"order_id": 1})
        v2 = self.d.register("shopify", {"order_id": 2})
        self.assertFalse(v2.seen)
        self.assertNotEqual(v1.digest, v2.digest)

    def test_different_sources_isolated(self) -> None:
        self.d.register("shopify", {"order_id": 1})
        v = self.d.register("meta", {"order_id": 1})
        self.assertFalse(v.seen)

    def test_key_order_canonicalised(self) -> None:
        v1 = self.d.register(
            "shopify", {"a": 1, "b": 2},
        )
        v2 = self.d.register(
            "shopify", {"b": 2, "a": 1},
        )
        self.assertTrue(v2.seen)
        self.assertEqual(v1.digest, v2.digest)

    def test_delivery_id_overrides_payload(self) -> None:
        v1 = self.d.register(
            "shopify", {"order_id": 1}, delivery_id="abc",
        )
        v2 = self.d.register(
            "shopify", {"order_id": 2}, delivery_id="abc",
        )
        # Same delivery_id → same digest even with different payload
        self.assertTrue(v2.seen)
        self.assertEqual(v1.digest, v2.digest)

    def test_blank_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.d.register("", {"x": 1})


class TestExpiry(unittest.TestCase):
    def test_expired_entry_allows_reprocess(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        d = wd.WebhookDedup(Path(tmp.name) / "w.db")
        d.register("shopify", {"order_id": 1}, ttl_s=0.05)
        time.sleep(0.1)
        v = d.register("shopify", {"order_id": 1}, ttl_s=0.05)
        self.assertFalse(v.seen)
        tmp.cleanup()


class TestSeen(unittest.TestCase):
    def test_seen_helper(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        d = wd.WebhookDedup(Path(tmp.name) / "w.db")
        v = d.register("shopify", {"order_id": 42})
        self.assertTrue(d.seen("shopify", v.digest))
        self.assertFalse(d.seen("shopify", "fake_digest"))
        tmp.cleanup()


class TestPurge(unittest.TestCase):
    def test_purge_by_source(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        d = wd.WebhookDedup(Path(tmp.name) / "w.db")
        d.register("shopify", {"x": 1})
        d.register("meta", {"x": 1})
        removed = d.purge(source="shopify")
        self.assertEqual(removed, 1)
        tmp.cleanup()

    def test_purge_by_age(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        d = wd.WebhookDedup(Path(tmp.name) / "w.db")
        d.register("shopify", {"x": 1})
        removed = d.purge(older_than_s=-1)  # everything
        self.assertEqual(removed, 1)
        tmp.cleanup()

    def test_default_purge_drops_expired(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        d = wd.WebhookDedup(Path(tmp.name) / "w.db")
        d.register("shopify", {"x": 1}, ttl_s=0.05)
        d.register("shopify", {"x": 2}, ttl_s=3600)
        time.sleep(0.1)
        removed = d.purge()
        self.assertEqual(removed, 1)
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        d = wd.WebhookDedup(Path(tmp.name) / "w.db")
        d.register("shopify", {"x": 1})
        d.register("shopify", {"x": 2})
        d.register("meta", {"x": 1})
        stats = d.stats()
        self.assertEqual(stats["live"], 3)
        self.assertEqual(stats["by_source"]["shopify"], 2)
        tmp.cleanup()


class TestSingleton(unittest.TestCase):
    def test_dedup_returns_same(self) -> None:
        self.assertIs(wd.dedup(), wd.dedup())


if __name__ == "__main__":
    unittest.main()
