"""Tests for autopilot's default video_prompts helper (A6 wire)."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from execution.launch import autopilot as ap
from agents.research.winner_searcher import (
    ProductCandidate, StaticWinnerSource,
)


class _EnableVideoGen:
    """Context manager that flips SHOPAI_VIDEO_GENERATE=1."""

    def __enter__(self):
        self._orig = os.environ.get("SHOPAI_VIDEO_GENERATE")
        os.environ["SHOPAI_VIDEO_GENERATE"] = "1"
        return self

    def __exit__(self, *a):
        if self._orig is None:
            os.environ.pop("SHOPAI_VIDEO_GENERATE", None)
        else:
            os.environ["SHOPAI_VIDEO_GENERATE"] = self._orig


def _candidate(**kw):
    defaults = dict(
        source="manual",
        external_id="sku-1",
        title="Pet Slow Feeder",
        price=29.99,
        cost=8.50,
        daily_sales=20,
        saturation_score=0.3,
        image_url="https://cdn.example/feeder.jpg",
        url="https://aliexpress.com/item/1",
    )
    defaults.update(kw)
    return ProductCandidate(**defaults)


class TestDefaultPromptsShape(unittest.TestCase):
    def test_two_volume_tier_prompts(self):
        with _EnableVideoGen():
            prompts = ap._default_video_prompts(_candidate())
        self.assertEqual(len(prompts), 2)
        for p in prompts:
            self.assertEqual(p["aspect"], "9:16")
            self.assertEqual(p["duration_s"], 5.0)
            self.assertEqual(p["quality_floor"], "volume")

    def test_title_included_in_prompts(self):
        with _EnableVideoGen():
            prompts = ap._default_video_prompts(
                _candidate(title="Unicorn Bowl"),
            )
        for p in prompts:
            self.assertIn("Unicorn Bowl", p["prompt"])

    def test_reference_image_on_first_prompt(self):
        with _EnableVideoGen():
            prompts = ap._default_video_prompts(_candidate())
        self.assertEqual(
            prompts[0]["reference_image_url"],
            "https://cdn.example/feeder.jpg",
        )
        self.assertNotIn("reference_image_url", prompts[1])

    def test_no_image_url_omits_reference(self):
        with _EnableVideoGen():
            prompts = ap._default_video_prompts(
                _candidate(image_url=""),
            )
        for p in prompts:
            self.assertNotIn("reference_image_url", p)


class TestEnvGate(unittest.TestCase):
    def test_gate_off_returns_empty(self):
        # Ensure env is not set
        orig = os.environ.pop(
            "SHOPAI_VIDEO_GENERATE", None,
        )
        try:
            prompts = ap._default_video_prompts(_candidate())
        finally:
            if orig is not None:
                os.environ["SHOPAI_VIDEO_GENERATE"] = orig
        self.assertEqual(prompts, [])

    def test_gate_on_returns_two(self):
        with _EnableVideoGen():
            prompts = ap._default_video_prompts(_candidate())
        self.assertEqual(len(prompts), 2)

    def test_owner_curation_bypasses_gate(self):
        """Owner-curated prompts run even when gate is off —
        explicit intent beats policy."""
        orig = os.environ.pop(
            "SHOPAI_VIDEO_GENERATE", None,
        )
        try:
            cand = _candidate()
            object.__setattr__(
                cand, "video_prompts",
                [{"prompt": "owner", "aspect": "16:9"}],
            )
            prompts = ap._default_video_prompts(cand)
        finally:
            if orig is not None:
                os.environ["SHOPAI_VIDEO_GENERATE"] = orig
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["prompt"], "owner")


class TestOwnerCurationRespected(unittest.TestCase):
    def test_existing_prompts_untouched(self):
        with _EnableVideoGen():
            cand = _candidate()
            # Attach owner-curated prompts via dynamic attr
            object.__setattr__(
                cand, "video_prompts",
                [{"prompt": "owner custom", "aspect": "16:9"}],
            )
            prompts = ap._default_video_prompts(cand)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(
            prompts[0]["prompt"], "owner custom",
        )
        self.assertEqual(prompts[0]["aspect"], "16:9")


class TestAutopilotFlowsPromptsThrough(unittest.TestCase):
    """Integration: Autopilot._run_one() must stamp
    video_prompts onto the winner_dict it hands to
    PublisherBundle."""

    def test_publisher_sees_video_prompts(self):
        captured = []

        class _CapturingPublisher:
            def launch(self, req):
                captured.append(req)
                from execution.launch.publisher_bundle import (
                    LaunchResult,
                )
                return LaunchResult(
                    decision_id=req.resolved_decision_id,
                    product_handle="h",
                    product_id="p",
                    campaign_id="c",
                    tracking_url="https://x",
                    steps=[],
                    ok=True,
                    dry_run=True,
                    note="",
                )

        class _FakeActivator:
            def activate(self, req):
                from execution.launch.campaign_activator import (
                    ActivationResult,
                )
                return ActivationResult(
                    decision_id=req.decision_id or "d",
                    campaign_id=req.campaign_id,
                    verdict="dry_run",
                    dry_run=True,
                    steps=[],
                )

        with _EnableVideoGen():
            pilot = ap.Autopilot(
                publisher_bundle=_CapturingPublisher(),
                campaign_activator=_FakeActivator(),
            )
            req = ap.AutopilotRequest(
                shop_url="s.myshopify.com",
                api_key="tok",
                winner_sources=[StaticWinnerSource([
                    _candidate(title="Thing"),
                ])],
                max_launches=1,
                ad_budget_daily=20.0,
                platform="facebook",
                meta_account_id="act_1",
                live=False,
            )
            pilot.run(req)
        self.assertEqual(len(captured), 1)
        winner_dict = captured[0].winner
        self.assertIn("video_prompts", winner_dict)
        prompts = winner_dict["video_prompts"]
        self.assertEqual(len(prompts), 2)
        self.assertIn("Thing", prompts[0]["prompt"])

    def test_publisher_gets_empty_prompts_when_gate_off(self):
        captured = []

        class _CapturingPublisher:
            def launch(self, req):
                captured.append(req)
                from execution.launch.publisher_bundle import (
                    LaunchResult,
                )
                return LaunchResult(
                    decision_id=req.resolved_decision_id,
                    product_handle="h",
                    product_id="p",
                    campaign_id="c",
                    tracking_url="https://x",
                    steps=[],
                    ok=True,
                    dry_run=True,
                    note="",
                )

        class _FakeActivator:
            def activate(self, req):
                from execution.launch.campaign_activator import (
                    ActivationResult,
                )
                return ActivationResult(
                    decision_id=req.decision_id or "d",
                    campaign_id=req.campaign_id,
                    verdict="dry_run",
                    dry_run=True,
                    steps=[],
                )

        orig = os.environ.pop(
            "SHOPAI_VIDEO_GENERATE", None,
        )
        try:
            pilot = ap.Autopilot(
                publisher_bundle=_CapturingPublisher(),
                campaign_activator=_FakeActivator(),
            )
            req = ap.AutopilotRequest(
                shop_url="s.myshopify.com",
                api_key="tok",
                winner_sources=[StaticWinnerSource([
                    _candidate(title="Thing"),
                ])],
                max_launches=1,
                ad_budget_daily=20.0,
                platform="facebook",
                meta_account_id="act_1",
                live=False,
            )
            pilot.run(req)
        finally:
            if orig is not None:
                os.environ["SHOPAI_VIDEO_GENERATE"] = orig
        self.assertEqual(len(captured), 1)
        winner_dict = captured[0].winner
        # Gate is off — helper returns [] and the daemon
        # publishes without requesting fal.ai generation.
        self.assertEqual(
            winner_dict.get("video_prompts"), [],
        )


if __name__ == "__main__":
    unittest.main()
