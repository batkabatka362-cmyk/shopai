"""A6 tests — fal video router wired into publisher_bundle."""
from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from execution.launch import publisher_bundle as pb


def _winner(**kw):
    base = dict(
        title="Pet Slow-Feeder Bowl",
        price=29.99,
        image_url="https://cdn.example/pet-bowl.jpg",
        margin_pct=0.65,
        source="aliexpress",
        sku="sku-pet-1",
    )
    base.update(kw)
    return base


def _request(**kw):
    defaults = dict(
        winner=_winner(),
        shop_url="example.myshopify.com",
        api_key="tok",
        ad_budget_daily=20.0,
        ad_objective="OUTCOME_SALES",
        platform="facebook",
        meta_account_id="act_1",
        live=False,
    )
    defaults.update(kw)
    return pb.LaunchRequest(**defaults)


class _FakeRouter:
    """Stand-in for FalVideoRouter."""

    def __init__(
        self, *, generate_results=None,
        pick_none=False,
    ) -> None:
        self._results = list(generate_results or [])
        self._pick_none = pick_none
        self.picked: list[Any] = []
        self.generated: list[Any] = []

    def pick_model(self, request):
        self.picked.append(request)
        if self._pick_none:
            return None
        return MagicMock(
            model_id="fal-ai/kling/v2.6-turbo",
            quality_tier="volume",
            price_per_sec=0.07,
        )

    def estimate_cost(self, *, model, duration_s):
        return round(model.price_per_sec * duration_s, 4)

    def generate(self, request):
        self.generated.append(request)
        if not self._results:
            from core.adapters.fal.video_router import (
                VideoResult,
            )
            return VideoResult(
                ok=False, error="no stub result",
            )
        return self._results.pop(0)


class TestNoPrompts(unittest.TestCase):
    def test_no_video_prompts_skips_step(self):
        bundle = pb.PublisherBundle(
            video_router=_FakeRouter(),
        )
        req = _request()  # no video_prompts on winner
        log = bundle._step_generate_videos(
            req, [], dry_run=True,
        )
        self.assertEqual(log.status, "success")
        self.assertEqual(
            log.data.get("note"),
            "no video_prompts on winner",
        )


class TestDryRun(unittest.TestCase):
    def test_dry_run_simulates_without_api_call(self):
        router = _FakeRouter()
        bundle = pb.PublisherBundle(video_router=router)
        req = _request(winner=_winner(
            video_prompts=[{
                "prompt": "pet bowl lifestyle shot",
                "duration_s": 5.0,
                "aspect": "9:16",
            }],
        ))
        log = bundle._step_generate_videos(
            req, [], dry_run=True,
        )
        self.assertEqual(log.status, "dry_run")
        self.assertEqual(len(router.generated), 0)
        self.assertEqual(len(router.picked), 1)
        creatives = log.data["creatives"]
        self.assertEqual(len(creatives), 1)
        self.assertTrue(creatives[0]["dry_run"])
        self.assertGreater(
            creatives[0]["estimated_cost_usd"], 0,
        )
        self.assertEqual(
            creatives[0]["c2pa"]["creator"], "shopai",
        )

    def test_dry_run_merges_into_ai_creatives(self):
        router = _FakeRouter()
        bundle = pb.PublisherBundle(video_router=router)
        req = _request(winner=_winner(
            video_prompts=[
                {"prompt": "A", "duration_s": 3.0},
                {"prompt": "B", "duration_s": 4.0},
            ],
        ))
        self.assertEqual(len(req.ai_creatives), 0)
        bundle._step_generate_videos(
            req, [], dry_run=True,
        )
        self.assertEqual(len(req.ai_creatives), 2)

    def test_dry_run_pick_none_records_error(self):
        router = _FakeRouter(pick_none=True)
        bundle = pb.PublisherBundle(video_router=router)
        req = _request(winner=_winner(
            video_prompts=[{
                "prompt": "x", "duration_s": 30.0,
            }],
        ))
        log = bundle._step_generate_videos(
            req, [], dry_run=True,
        )
        self.assertEqual(log.status, "error")


class TestLive(unittest.TestCase):
    def test_live_call_invokes_router(self):
        from core.adapters.fal.video_router import (
            VideoResult,
        )
        router = _FakeRouter(generate_results=[
            VideoResult(
                ok=True,
                model_id="fal-ai/kling/v2.6-turbo",
                video_url="https://cdn.fal/abc.mp4",
                cost_usd=0.35,
                duration_s=5.0,
                request_id="req_1",
            ),
        ])
        bundle = pb.PublisherBundle(video_router=router)
        req = _request(winner=_winner(
            video_prompts=[{
                "prompt": "live promo",
                "duration_s": 5.0,
            }],
        ))
        log = bundle._step_generate_videos(
            req, [], dry_run=False,
        )
        self.assertEqual(log.status, "success")
        self.assertEqual(len(router.generated), 1)
        self.assertAlmostEqual(
            log.data["total_cost_usd"], 0.35,
        )
        creative = log.data["creatives"][0]
        self.assertEqual(
            creative["url"], "https://cdn.fal/abc.mp4",
        )
        self.assertEqual(creative["media_kind"], "video")

    def test_live_all_fail_surfaces_error(self):
        from core.adapters.fal.video_router import (
            VideoResult,
        )
        router = _FakeRouter(generate_results=[
            VideoResult(
                ok=False,
                model_id="fal-ai/kling/v2.6-turbo",
                error="HTTP 429",
            ),
        ])
        bundle = pb.PublisherBundle(video_router=router)
        req = _request(winner=_winner(
            video_prompts=[{
                "prompt": "x", "duration_s": 5.0,
            }],
        ))
        log = bundle._step_generate_videos(
            req, [], dry_run=False,
        )
        self.assertEqual(log.status, "error")
        self.assertIn("HTTP 429", log.error)


class TestRouterUnavailable(unittest.TestCase):
    def test_no_router_skipped_cleanly(self):
        bundle = pb.PublisherBundle(video_router=None)
        # Monkeypatch the lazy loader to simulate missing dep
        bundle._get_video_router = lambda: None  # type: ignore[assignment]
        req = _request(winner=_winner(
            video_prompts=[{"prompt": "x"}],
        ))
        log = bundle._step_generate_videos(
            req, [], dry_run=True,
        )
        self.assertEqual(log.status, "success")
        self.assertIn(
            "unavailable", log.data.get("note", ""),
        )


class TestLaunchIntegration(unittest.TestCase):
    def test_launch_runs_video_step_end_to_end(self):
        from tests.test_publisher_bundle import (
            _FakeAds, _FakeContent, _FakeOutcomes,
            _FakeProducts, _FakeRationale,
        )
        router = _FakeRouter()  # dry-run path
        bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(),
            ad_adapter=_FakeAds(success=True),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=_FakeRationale(),
            video_router=router,
        )
        req = _request(winner=_winner(
            video_prompts=[
                {"prompt": "demo", "duration_s": 5.0},
            ],
        ))
        result = bundle.launch(req)
        self.assertTrue(result.ok)
        names = [s.name for s in result.steps]
        self.assertIn("video_generate", names)
        # Video step ran before EU gate
        self.assertLess(
            names.index("video_generate"),
            names.index("eu_ai_compliance"),
        )


if __name__ == "__main__":
    unittest.main()
