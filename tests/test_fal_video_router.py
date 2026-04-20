"""Tests for core.adapters.fal.video_router (Wave D-1)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.adapters.fal.video_router import (
    FalVideoRouter,
    VideoModel,
    VideoRequest,
    VideoResult,
)


def _resp(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = payload or {}
    return r


def _build(tmp, *, http=None, api_key="fal_test", cap=10.0,
           now=1_700_000_000.0):
    return FalVideoRouter(
        api_key=api_key,
        http=http or MagicMock(),
        db_path=Path(tmp) / "fal.db",
        weekly_cap_usd=cap,
        now_fn=lambda: now,
    )


class TestRequestValidation(unittest.TestCase):
    def test_blank_sku_raises(self):
        with self.assertRaises(ValueError):
            VideoRequest(sku="", prompt="x")

    def test_blank_prompt_raises(self):
        with self.assertRaises(ValueError):
            VideoRequest(sku="s", prompt="")

    def test_zero_duration_raises(self):
        with self.assertRaises(ValueError):
            VideoRequest(
                sku="s", prompt="x", duration_s=0,
            )


class TestModelPicking(unittest.TestCase):
    def test_volume_picks_cheapest(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp)
            req = VideoRequest(
                sku="s", prompt="x",
                aspect="9:16", duration_s=5,
                quality_floor="volume",
            )
            m = r.pick_model(req)
            self.assertIsNotNone(m)
            self.assertEqual(m.quality_tier, "volume")
            self.assertAlmostEqual(
                m.price_per_sec, 0.07,
            )
            r.close()

    def test_hero_excludes_volume_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp)
            m = r.pick_model(VideoRequest(
                sku="s", prompt="x",
                quality_floor="hero",
            ))
            self.assertEqual(m.quality_tier, "hero")
            r.close()

    def test_premium_picks_veo(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp)
            m = r.pick_model(VideoRequest(
                sku="s", prompt="x",
                quality_floor="premium",
                duration_s=8,
            ))
            self.assertEqual(
                m.quality_tier, "premium",
            )
            r.close()

    def test_aspect_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 4:3 isn't in any default model
            r = _build(tmp)
            m = r.pick_model(VideoRequest(
                sku="s", prompt="x", aspect="4:3",
            ))
            self.assertIsNone(m)
            r.close()

    def test_duration_too_long(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp)
            m = r.pick_model(VideoRequest(
                sku="s", prompt="x", duration_s=30,
            ))
            self.assertIsNone(m)
            r.close()


class TestCostAndCap(unittest.TestCase):
    def test_estimate_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp)
            model = r.pick_model(VideoRequest(
                sku="s", prompt="x", duration_s=5,
            ))
            self.assertAlmostEqual(
                r.estimate_cost(
                    model=model, duration_s=10,
                ),
                0.70,
                places=4,
            )
            r.close()

    def test_weekly_cap_blocks(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"video_url": "https://v/1"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp, http=http, cap=0.50)
            result = r.generate(VideoRequest(
                sku="sku1", prompt="test",
                duration_s=10,
            ))
            # 0.07 × 10 = 0.70 > 0.50 cap → skip
            self.assertFalse(result.ok)
            self.assertIn(
                "cap", result.skipped_reason,
            )
            r.close()

    def test_accumulates_spend(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"video_url": "https://v/1"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp, http=http, cap=10.0)
            for _ in range(3):
                res = r.generate(VideoRequest(
                    sku="sku1", prompt="t",
                    duration_s=5,
                ))
                self.assertTrue(res.ok)
            self.assertAlmostEqual(
                r.spent_this_week("sku1"),
                3 * 0.07 * 5, places=2,
            )
            r.close()


class TestGenerate(unittest.TestCase):
    def test_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp, api_key="")
            result = r.generate(VideoRequest(
                sku="s", prompt="x",
            ))
            self.assertFalse(result.ok)
            self.assertIn(
                "FAL_KEY",
                result.skipped_reason,
            )
            r.close()

    def test_happy_path(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200,
            payload={
                "video": {
                    "url": "https://v/clip.mp4",
                },
                "request_id": "req123",
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp, http=http)
            result = r.generate(VideoRequest(
                sku="s", prompt="a dog",
                duration_s=5,
            ))
            self.assertTrue(result.ok)
            self.assertEqual(
                result.video_url,
                "https://v/clip.mp4",
            )
            self.assertEqual(
                result.request_id, "req123",
            )
            self.assertAlmostEqual(
                result.cost_usd, 0.35, places=2,
            )
            r.close()

    def test_http_error(self):
        http = MagicMock()
        http.post.return_value = _resp(
            500, text="down",
        )
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp, http=http)
            res = r.generate(VideoRequest(
                sku="s", prompt="x", duration_s=5,
            ))
            self.assertFalse(res.ok)
            self.assertIn("500", res.error)
            r.close()

    def test_network_exception(self):
        http = MagicMock()
        http.post.side_effect = RuntimeError("conn")
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp, http=http)
            res = r.generate(VideoRequest(
                sku="s", prompt="x",
            ))
            self.assertFalse(res.ok)
            self.assertIn("network", res.error)
            r.close()

    def test_missing_video_url(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"status": "done"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp, http=http)
            res = r.generate(VideoRequest(
                sku="s", prompt="x",
            ))
            self.assertFalse(res.ok)
            self.assertIn(
                "no video_url", res.error,
            )
            r.close()

    def test_bearer_header(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"video_url": "https://v/1"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp, http=http)
            r.generate(VideoRequest(
                sku="s", prompt="x",
            ))
            headers = (
                http.post.call_args.kwargs["headers"]
            )
            self.assertEqual(
                headers["Authorization"],
                "Key fal_test",
            )
            r.close()


class TestStats(unittest.TestCase):
    def test_stats_shape(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"video_url": "https://v/1"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            r = _build(tmp, http=http)
            r.generate(VideoRequest(
                sku="s", prompt="x",
            ))
            s = r.stats()
            self.assertEqual(s["total_generations"], 1)
            self.assertTrue(s["configured"])
            self.assertGreater(s["total_spend_usd"], 0)
            r.close()


class TestDicts(unittest.TestCase):
    def test_model_dict(self):
        m = VideoModel(
            model_id="x",
            quality_tier="volume",
            price_per_sec=0.07,
            max_duration_s=10.0,
            aspect_ratios=("9:16",),
        )
        self.assertIn(
            "price_per_sec", m.as_dict(),
        )

    def test_request_dict(self):
        req = VideoRequest(sku="s", prompt="p")
        self.assertEqual(req.as_dict()["sku"], "s")

    def test_result_dict(self):
        res = VideoResult(ok=False, error="x")
        self.assertFalse(res.as_dict()["ok"])


if __name__ == "__main__":
    unittest.main()
