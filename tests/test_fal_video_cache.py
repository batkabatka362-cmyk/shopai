"""Tests for the fal.ai pre-generation cache (P2.7)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.adapters.fal.video_router import (
    FalVideoRouter,
    VideoRequest,
    VideoResult,
    _prompt_hash,
)


def _ok_resp(url: str = "https://cdn/x.mp4") -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {
        "video": {"url": url},
        "request_id": "r-1",
    }
    return r


def _build(
    tmp: tempfile.TemporaryDirectory,
    *,
    http=None,
    api_key="fal_key",
    cap=100.0,
    cache_ttl_days=30.0,
    now_fn=None,
) -> FalVideoRouter:
    return FalVideoRouter(
        api_key=api_key,
        http=http or MagicMock(),
        db_path=Path(tmp.name) / "fal.db",
        weekly_cap_usd=cap,
        cache_ttl_days=cache_ttl_days,
        now_fn=now_fn or (lambda: 1_800_000_000.0),
    )


class TestPromptHash(unittest.TestCase):
    def test_stable_across_calls(self):
        a = _prompt_hash(
            model_id="m",
            prompt="pet bowl",
            aspect="9:16",
            duration_s=5.0,
        )
        b = _prompt_hash(
            model_id="m",
            prompt="pet bowl",
            aspect="9:16",
            duration_s=5.0,
        )
        self.assertEqual(a, b)

    def test_case_and_whitespace_insensitive(self):
        a = _prompt_hash(
            model_id="m",
            prompt="Pet Bowl",
            aspect="9:16",
            duration_s=5.0,
        )
        b = _prompt_hash(
            model_id="m",
            prompt="  pet bowl  ",
            aspect="9:16",
            duration_s=5.0,
        )
        self.assertEqual(a, b)

    def test_different_model_different_hash(self):
        a = _prompt_hash(
            model_id="m1",
            prompt="p",
            aspect="9:16",
            duration_s=5.0,
        )
        b = _prompt_hash(
            model_id="m2",
            prompt="p",
            aspect="9:16",
            duration_s=5.0,
        )
        self.assertNotEqual(a, b)

    def test_seed_bypass(self):
        """seed=N produces a unique hash even for otherwise
        identical inputs — lets callers opt out of cache."""
        a = _prompt_hash(
            model_id="m", prompt="p",
            aspect="9:16", duration_s=5.0,
            seed=0,
        )
        b = _prompt_hash(
            model_id="m", prompt="p",
            aspect="9:16", duration_s=5.0,
            seed=42,
        )
        self.assertNotEqual(a, b)


class TestCacheLifecycle(unittest.TestCase):
    def test_first_call_misses_then_stores(self):
        with tempfile.TemporaryDirectory() as td:
            http = MagicMock()
            http.post.return_value = _ok_resp()
            r = _build(
                tempfile.TemporaryDirectory.__new__(
                    tempfile.TemporaryDirectory,
                ) if False else type(
                    "T", (), {"name": td},
                )(),
                http=http,
            )
            req = VideoRequest(
                sku="sku-1", prompt="pet bowl",
                duration_s=5.0,
            )
            res = r.generate(req)
            self.assertTrue(res.ok)
            self.assertEqual(res.cost_usd, 0.35)
            # One upstream call so far
            self.assertEqual(http.post.call_count, 1)
            # Cache persisted
            s = r.stats()
            self.assertEqual(s["cache_entries"], 1)
            self.assertEqual(s["cache_hits"], 0)
            r.close()

    def test_second_call_hits_cache_zero_cost(self):
        with tempfile.TemporaryDirectory() as td:
            http = MagicMock()
            http.post.return_value = _ok_resp(
                url="https://cdn/a.mp4",
            )
            r = _build(
                type("T", (), {"name": td})(),
                http=http,
            )
            req1 = VideoRequest(
                sku="sku-1", prompt="pet bowl",
                duration_s=5.0,
            )
            r.generate(req1)
            req2 = VideoRequest(
                sku="sku-OTHER", prompt="pet bowl",
                duration_s=5.0,
            )
            res = r.generate(req2)
            # cache hit: zero cost + request_id sentinel
            self.assertTrue(res.ok)
            self.assertEqual(res.cost_usd, 0.0)
            self.assertEqual(res.request_id, "cache")
            self.assertEqual(
                res.video_url, "https://cdn/a.mp4",
            )
            # No second upstream call
            self.assertEqual(http.post.call_count, 1)
            s = r.stats()
            self.assertEqual(s["cache_hits"], 1)
            r.close()

    def test_cache_bypass_when_unconfigured(self):
        """Miss path with no API key must still return the
        skipped_reason (cost has already been paid on the
        earlier cache-populating call — but we skip the
        cache lookup check for the unconfigured case)."""
        with tempfile.TemporaryDirectory() as td:
            r = _build(
                type("T", (), {"name": td})(),
                api_key="",
            )
            req = VideoRequest(
                sku="s", prompt="uncached prompt",
                duration_s=5.0,
            )
            res = r.generate(req)
            self.assertFalse(res.ok)
            self.assertIn("not set", res.skipped_reason)
            r.close()

    def test_cache_wins_even_if_api_key_missing(self):
        """Owner might populate cache then rotate keys —
        cached hits should still work."""
        with tempfile.TemporaryDirectory() as td:
            http = MagicMock()
            http.post.return_value = _ok_resp()
            # First, populate cache with a configured router
            r1 = _build(
                type("T", (), {"name": td})(),
                http=http,
            )
            req = VideoRequest(
                sku="s", prompt="pet bowl",
                duration_s=5.0,
            )
            r1.generate(req)
            r1.close()
            # Now a new router pointing at the same DB with
            # NO key — cache should still satisfy the hit.
            r2 = _build(
                type("T", (), {"name": td})(),
                api_key="",
            )
            res = r2.generate(req)
            self.assertTrue(res.ok)
            self.assertEqual(res.request_id, "cache")
            r2.close()

    def test_ttl_expiry(self):
        with tempfile.TemporaryDirectory() as td:
            http = MagicMock()
            http.post.return_value = _ok_resp()
            # Clock advances so TTL expires
            clock = [1_800_000_000.0]
            r = _build(
                type("T", (), {"name": td})(),
                http=http,
                cache_ttl_days=1.0,
                now_fn=lambda: clock[0],
            )
            req = VideoRequest(
                sku="s", prompt="ttl test",
                duration_s=5.0,
            )
            r.generate(req)
            # 2 days later — cached row is stale, dropped,
            # re-generated.
            clock[0] += 2 * 86400.0
            http.post.return_value = _ok_resp(
                url="https://cdn/new.mp4",
            )
            res = r.generate(req)
            self.assertEqual(
                res.video_url, "https://cdn/new.mp4",
            )
            self.assertEqual(http.post.call_count, 2)
            r.close()

    def test_clear_cache(self):
        with tempfile.TemporaryDirectory() as td:
            http = MagicMock()
            http.post.return_value = _ok_resp()
            r = _build(
                type("T", (), {"name": td})(),
                http=http,
            )
            r.generate(VideoRequest(
                sku="s", prompt="one", duration_s=5.0,
            ))
            r.generate(VideoRequest(
                sku="s", prompt="two", duration_s=5.0,
            ))
            self.assertEqual(
                r.stats()["cache_entries"], 2,
            )
            n = r.clear_cache()
            self.assertEqual(n, 2)
            self.assertEqual(
                r.stats()["cache_entries"], 0,
            )
            r.close()

    def test_cache_stats_includes_hits(self):
        with tempfile.TemporaryDirectory() as td:
            http = MagicMock()
            http.post.return_value = _ok_resp()
            r = _build(
                type("T", (), {"name": td})(),
                http=http,
            )
            req = VideoRequest(
                sku="s", prompt="x", duration_s=5.0,
            )
            r.generate(req)  # miss
            r.generate(req)  # hit
            r.generate(req)  # hit
            cs = r.cache_stats()
            self.assertEqual(cs["entries"], 1)
            self.assertEqual(cs["total_hits"], 2)
            r.close()


class TestSeedBypass(unittest.TestCase):
    def test_unique_seeds_separate_cache_rows(self):
        with tempfile.TemporaryDirectory() as td:
            http = MagicMock()
            http.post.return_value = _ok_resp()
            r = _build(
                type("T", (), {"name": td})(),
                http=http,
            )
            r.generate(VideoRequest(
                sku="a", prompt="p",
                duration_s=5.0, seed=1,
            ))
            r.generate(VideoRequest(
                sku="b", prompt="p",
                duration_s=5.0, seed=2,
            ))
            self.assertEqual(
                r.stats()["cache_entries"], 2,
            )
            self.assertEqual(http.post.call_count, 2)
            r.close()


if __name__ == "__main__":
    unittest.main()
