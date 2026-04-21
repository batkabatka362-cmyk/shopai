"""Tests for MobyAdapter.recommendations() 5-minute TTL cache."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.adapters.triplewhale.moby import MobyAdapter


def _resp(payload=None):
    r = MagicMock()
    r.status_code = 200
    r.text = ""
    r.json.return_value = payload or {
        "data": [
            {
                "entity_id": "c-1",
                "recommendation": "pause",
                "confidence": 0.7,
                "roas_delta": 0.0,
            },
        ],
    }
    return r


def _build(tmp, http, now_fn):
    return MobyAdapter(
        api_key="tw_test",
        http=http,
        db_path=Path(tmp) / "moby.db",
        now_fn=now_fn,
    )


class TestCache(unittest.TestCase):
    def test_second_call_uses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = MagicMock()
            http.get.return_value = _resp()
            t = [1_000_000.0]
            a = _build(tmp, http, now_fn=lambda: t[0])
            # First call hits API
            recs1 = a.recommendations(scope="campaigns")
            self.assertEqual(len(recs1), 1)
            self.assertEqual(http.get.call_count, 1)
            # Second call 30s later uses cache
            t[0] += 30
            recs2 = a.recommendations(scope="campaigns")
            self.assertEqual(len(recs2), 1)
            self.assertEqual(http.get.call_count, 1)
            a.close()

    def test_cache_expires_after_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = MagicMock()
            http.get.return_value = _resp()
            t = [1_000_000.0]
            a = _build(tmp, http, now_fn=lambda: t[0])
            a.recommendations(scope="campaigns")
            self.assertEqual(http.get.call_count, 1)
            # 301 seconds later — past 300s TTL
            t[0] += 301
            a.recommendations(scope="campaigns")
            self.assertEqual(http.get.call_count, 2)
            a.close()

    def test_force_bypasses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = MagicMock()
            http.get.return_value = _resp()
            t = [1_000_000.0]
            a = _build(tmp, http, now_fn=lambda: t[0])
            a.recommendations(scope="campaigns")
            # Immediate second call with force=True
            a.recommendations(scope="campaigns", force=True)
            self.assertEqual(http.get.call_count, 2)
            a.close()

    def test_different_scope_is_separate_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = MagicMock()
            http.get.return_value = _resp()
            t = [1_000_000.0]
            a = _build(tmp, http, now_fn=lambda: t[0])
            a.recommendations(scope="campaigns")
            a.recommendations(scope="creatives")
            # Each scope gets its own upstream call
            self.assertEqual(http.get.call_count, 2)
            # But repeating campaigns is cached
            a.recommendations(scope="campaigns")
            self.assertEqual(http.get.call_count, 2)
            a.close()

    def test_different_limit_is_separate_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = MagicMock()
            http.get.return_value = _resp()
            t = [1_000_000.0]
            a = _build(tmp, http, now_fn=lambda: t[0])
            a.recommendations(scope="campaigns", limit=20)
            a.recommendations(scope="campaigns", limit=50)
            self.assertEqual(http.get.call_count, 2)
            a.close()

    def test_cache_returns_copy_not_mutation_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = MagicMock()
            http.get.return_value = _resp()
            t = [1_000_000.0]
            a = _build(tmp, http, now_fn=lambda: t[0])
            first = a.recommendations(scope="campaigns")
            first.clear()
            # Second call returns fresh list from cache —
            # caller mutation of the first result doesn't
            # corrupt the cache.
            second = a.recommendations(scope="campaigns")
            self.assertEqual(len(second), 1)
            a.close()


if __name__ == "__main__":
    unittest.main()
