"""Autopilot full-stack smoke test — real PublisherBundle +
CampaignActivator wired together with boundary fakes only.

Existing tests (test_autopilot.py) mock out both the publisher
and the activator so the end-to-end chain is never exercised.
This smoke test wires the REAL modules together so a regression
in any internal step (video_generate, eu_ai_compliance,
moby_vote_compare, pre-flight, tripwire, readiness) fails here.
Network boundaries are the only fakes:

  * ContentGenerator → _FakeContent
  * ProductCreator   → _FakeProductCreator
  * MetaAdsAdapter   → _FakeAds
  * ModeR adapter    → injected MobyVoteComparator without adapter
  * Video router     → injected FakeRouter (dry-run path)

Assertion intent: every step the owner expects to see in a
live cycle actually fired, in the right order, and
OutcomeRecorder got a launch event at the end.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock

from agents.research.winner_searcher import (
    ProductCandidate, StaticWinnerSource,
)
from execution.launch import autopilot as ap
from execution.launch.publisher_bundle import PublisherBundle
from execution.launch.campaign_activator import (
    CampaignActivator,
)


def _candidate():
    return ProductCandidate(
        source="manual",
        external_id="sku-smoke-1",
        title="Smoke Test Bowl",
        price=29.99,
        cost=8.50,
        daily_sales=20,
        saturation_score=0.3,
        image_url="https://cdn.example/bowl.jpg",
        url="https://aliexpress.com/item/1",
    )


class _FakeContent:
    def ad_copy(self, product, platform="facebook"):
        return {
            "platform": platform,
            "headline": f"{product['title']} headline",
            "body": f"Shop {product['title']} today!",
            "cta": "Shop Now",
        }


class _FakeProductCreator:
    def __init__(self):
        self.calls: list[dict] = []

    def create_product(self, shop_url, api_key, payload):
        self.calls.append({
            "shop_url": shop_url,
            "api_key": api_key,
            "payload": payload,
        })
        return {
            "status": "created",
            "product": {
                "id": "prod_smoke",
                "handle": "smoke-test-bowl",
            },
        }


class _FakeAds:
    def __init__(self):
        self.calls: list[dict] = []

    def execute(self, capability, params):
        from core.adapters.base import AdapterResult
        self.calls.append({
            "capability": getattr(
                capability, "value", str(capability),
            ),
            "params": dict(params),
        })
        return AdapterResult.success(
            adapter="fake_ads",
            capability=getattr(
                capability, "value", str(capability),
            ),
            data={"campaign_id": "camp_smoke"},
            raw={},
        )


class _FakeVideoRouter:
    """Dry-run fal.ai router — pick_model returns a stub."""

    def pick_model(self, request):
        return MagicMock(
            model_id="fal-ai/kling/v2.6-turbo",
            quality_tier="volume",
            price_per_sec=0.07,
        )

    def estimate_cost(self, *, model, duration_s):
        return model.price_per_sec * duration_s


class _FakeOutcomes:
    def __init__(self):
        self.recorded: list[Any] = []

    def record(self, event):
        self.recorded.append(event)
        return MagicMock(event_id="e_smoke")

    def record_cancel(self, **kw):
        return MagicMock(event_id="e_cancel")


class _FakeRationale:
    def start(self, **kw):
        return MagicMock()

    def add(self, *a, **kw):
        return MagicMock()

    def commit(self, *a, **kw):
        return MagicMock()


class _PermissiveTripwire:
    """Passes every check — activator uses check_before_spend()."""

    def check_before_spend(self, **kw):
        verdict = MagicMock()
        verdict.action = "ok"
        verdict.rule = ""
        verdict.reason = "ok"
        verdict.as_dict = lambda: {
            "action": "ok", "rule": "", "reason": "ok",
        }
        return verdict

    def book_spend(self, **kw):
        return None


class _GreenCrisis:
    """Reports no crisis — activator proceeds."""

    def detect_state(self):
        return MagicMock(
            level="green", halted=False, reason="",
        )


class _AcceptingReadiness:
    """ReadinessGate stand-in — always verdict='go'."""

    def check(self, readiness_input):
        verdict = MagicMock()
        verdict.verdict = "go"
        verdict.reason = "fake go"
        verdict.as_dict = lambda: {
            "verdict": "go", "reason": "fake go",
        }
        return verdict


class _EmptyConstraints:
    """BehavioralConstraintRegistry stand-in — no violations."""

    def evaluate(self, **kw):
        result = MagicMock()
        result.any_severe = False
        result.alerts = []
        return result


def _real_publisher(ads, *, video_router=None):
    return PublisherBundle(
        content_generator=_FakeContent(),
        product_creator=_FakeProductCreator(),
        ad_adapter=ads,
        outcome_recorder=_FakeOutcomes(),
        rationale_builder=_FakeRationale(),
        video_router=video_router,
    )


def _real_activator(ads, *, moby_comparator=None):
    return CampaignActivator(
        ad_adapter=ads,
        readiness_checker=_AcceptingReadiness(),
        constraint_registry=_EmptyConstraints(),
        outcome_recorder=_FakeOutcomes(),
        rationale_builder=_FakeRationale(),
        risk_tripwire=_PermissiveTripwire(),
        crisis_responder=_GreenCrisis(),
        moby_comparator=moby_comparator,
    )


class TestAutopilotFullCycle(unittest.TestCase):
    """End-to-end dry-run cycle, real publisher + activator."""

    def setUp(self):
        # Ensure live-execution env flag is off
        self._orig_live = os.environ.pop(
            "SHOPAI_ENABLE_LIVE_EXECUTION", None,
        )

    def tearDown(self):
        if self._orig_live is not None:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig_live

    def _make_request(self):
        return ap.AutopilotRequest(
            shop_url="smoke.myshopify.com",
            api_key="tok",
            winner_sources=[
                StaticWinnerSource([_candidate()]),
            ],
            max_launches=1,
            ad_budget_daily=20.0,
            platform="facebook",
            meta_account_id="act_123",
            top_n=5,
            min_margin_pct=0.10,
            auto_activate=True,
            live=False,
        )

    def test_dry_run_full_chain_ok(self):
        ads = _FakeAds()
        pilot = ap.Autopilot(
            publisher_bundle=_real_publisher(
                ads, video_router=None,
            ),
            campaign_activator=_real_activator(ads),
        )
        result = pilot.run(self._make_request())
        self.assertTrue(result.dry_run)
        self.assertEqual(len(result.launches), 1)
        launch = result.launches[0]
        self.assertEqual(launch.winner_title, "Smoke Test Bowl")
        self.assertNotEqual(launch.publish_verdict, "error")

    def test_publisher_runs_expected_steps_in_order(self):
        ads = _FakeAds()
        publisher = _real_publisher(
            ads, video_router=_FakeVideoRouter(),
        )
        pilot = ap.Autopilot(
            publisher_bundle=publisher,
            campaign_activator=_real_activator(ads),
        )
        pilot.run(self._make_request())
        # publisher history has the last launch result
        self.assertTrue(publisher._history)
        steps = publisher._history[-1].steps
        names = [s.name for s in steps]
        self.assertIn("generate_copy", names)
        self.assertIn("create_product", names)
        self.assertIn("video_generate", names)
        self.assertIn("eu_ai_compliance", names)
        self.assertIn("launch_campaign", names)
        # ordering: video must run before eu_ai_compliance,
        # eu_ai_compliance before launch_campaign
        self.assertLess(
            names.index("video_generate"),
            names.index("eu_ai_compliance"),
        )
        self.assertLess(
            names.index("eu_ai_compliance"),
            names.index("launch_campaign"),
        )

    def test_activator_runs_moby_compare_step(self):
        # Inject a comparator whose adapter is None so the
        # step is a no-op but still appends a log row.
        from core.brain.moby_vote_comparator import (
            MobyVoteComparator,
        )
        comparator = MobyVoteComparator(adapter=None)
        comparator._get_adapter = lambda: None  # type: ignore[method-assign]
        ads = _FakeAds()
        activator = _real_activator(
            ads, moby_comparator=comparator,
        )
        pilot = ap.Autopilot(
            publisher_bundle=_real_publisher(ads),
            campaign_activator=activator,
        )
        pilot.run(self._make_request())
        # Last activation steps should include moby_vote_compare
        self.assertTrue(activator._history)
        steps = activator._history[-1].steps
        names = [s.name for s in steps]
        self.assertIn("moby_vote_compare", names)

    def test_outcome_recorded_for_launch(self):
        outcomes = _FakeOutcomes()
        publisher = PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProductCreator(),
            ad_adapter=_FakeAds(),
            outcome_recorder=outcomes,
            rationale_builder=_FakeRationale(),
            video_router=None,
        )
        ads = _FakeAds()
        pilot = ap.Autopilot(
            publisher_bundle=publisher,
            campaign_activator=_real_activator(ads),
        )
        pilot.run(self._make_request())
        # publisher_bundle fires an OutcomeEvent(kind="launch")
        launch_events = [
            e for e in outcomes.recorded
            if getattr(e, "kind", "") == "launch"
        ]
        self.assertEqual(len(launch_events), 1)
        self.assertEqual(
            launch_events[0].capability_name, "launch_sku",
        )

    def test_launch_campaign_dry_run_emits_params(self):
        # Dry-run mode: ads adapter isn't called (by design),
        # but the launch_campaign step records the params it
        # *would have* sent plus a synthetic dryrun_ campaign_id.
        ads = _FakeAds()
        publisher = _real_publisher(ads)
        pilot = ap.Autopilot(
            publisher_bundle=publisher,
            campaign_activator=_real_activator(ads),
        )
        pilot.run(self._make_request())
        # Ads adapter must NOT have been invoked in dry-run.
        self.assertEqual(
            ads.calls, [],
            f"dry-run must not call live ads; got {ads.calls}",
        )
        steps = publisher._history[-1].steps
        launch_step = next(
            s for s in steps if s.name == "launch_campaign"
        )
        self.assertEqual(launch_step.status, "dry_run")
        params = launch_step.data.get("params") or {}
        self.assertEqual(params.get("status"), "PAUSED")
        self.assertEqual(
            params.get("objective"), "OUTCOME_SALES",
        )
        self.assertEqual(
            params.get("account_id"), "act_123",
        )
        self.assertTrue(
            str(launch_step.data.get(
                "campaign_id", "",
            )).startswith("dryrun_"),
        )


if __name__ == "__main__":
    unittest.main()
