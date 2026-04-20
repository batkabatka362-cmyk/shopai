"""Autopilot end-to-end tests (all fakes — no network)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from agents.research.sources.manual_seed import (
    ManualSeedSource,
)
from agents.research.winner_searcher import (
    ProductCandidate, StaticWinnerSource,
)
from execution.launch import autopilot as ap


# ── Fakes ───────────────────────────────────────────────────


def _winner_dict(**kw):
    base = dict(
        title="Pet Slow Feeder",
        price=29.99,
        cost=8.50,
        daily_sales=20,
        saturation_score=0.3,
        image_url="https://cdn.example/feeder.jpg",
        url="https://aliexpress.com/item/1",
        source="manual",
        external_id="ali-1",
    )
    base.update(kw)
    return base


def _static_source(*winners):
    candidates = [
        ProductCandidate(
            source=w.get("source", "manual"),
            external_id=w["external_id"],
            title=w["title"],
            price=w["price"],
            cost=w["cost"],
            daily_sales=w["daily_sales"],
            saturation_score=w["saturation_score"],
            image_url=w.get("image_url", ""),
            url=w.get("url", ""),
        )
        for w in winners
    ]
    return StaticWinnerSource(candidates)


class _FakePublisher:
    def __init__(
        self,
        *, ok: bool = True,
        campaign_id: str = "camp_abc",
        product_id: str = "prod_99",
    ):
        self._ok = ok
        self._campaign_id = campaign_id
        self._product_id = product_id
        self.calls: list[Any] = []

    def launch(self, req):
        from execution.launch.publisher_bundle import (
            LaunchResult,
        )
        self.calls.append(req)
        decision_id = req.resolved_decision_id
        return LaunchResult(
            decision_id=decision_id,
            product_handle="pet-feeder",
            product_id=self._product_id,
            campaign_id=self._campaign_id if self._ok else "",
            tracking_url="https://x/track",
            steps=[],
            ok=self._ok,
            dry_run=not req.live,
            note="" if self._ok else "fake failure",
        )


class _FakeActivator:
    def __init__(self, verdict="activated"):
        self._verdict = verdict
        self.calls: list[Any] = []

    def activate(self, req):
        from execution.launch.campaign_activator import (
            ActivationResult,
        )
        self.calls.append(req)
        return ActivationResult(
            decision_id=req.decision_id or "dec_x",
            campaign_id=req.campaign_id,
            verdict=self._verdict,
            dry_run=self._verdict == "dry_run",
            steps=[],
            block_reason=(
                "fake block"
                if self._verdict == "blocked" else ""
            ),
        )


# ── Request validation ─────────────────────────────────────


class TestRequest(unittest.TestCase):
    def test_blank_shop_raises(self):
        with self.assertRaises(ValueError):
            ap.AutopilotRequest(
                shop_url="",
                api_key="tok",
                winner_sources=[_static_source(_winner_dict())],
            )

    def test_live_requires_api_key(self):
        with self.assertRaises(ValueError):
            ap.AutopilotRequest(
                shop_url="s.myshopify.com",
                api_key="",
                winner_sources=[_static_source(_winner_dict())],
                live=True,
            )

    def test_empty_sources_raises(self):
        with self.assertRaises(ValueError):
            ap.AutopilotRequest(
                shop_url="s.myshopify.com",
                api_key="tok",
                winner_sources=[],
            )

    def test_bad_max_launches_raises(self):
        with self.assertRaises(ValueError):
            ap.AutopilotRequest(
                shop_url="s.myshopify.com",
                api_key="tok",
                winner_sources=[_static_source(_winner_dict())],
                max_launches=0,
            )

    def test_bad_platform_raises(self):
        with self.assertRaises(ValueError):
            ap.AutopilotRequest(
                shop_url="s.myshopify.com",
                api_key="tok",
                winner_sources=[_static_source(_winner_dict())],
                platform="snapchat",
            )


# ── End-to-end ──────────────────────────────────────────────


class TestDryRun(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.pop(
            "SHOPAI_ENABLE_LIVE_EXECUTION", None,
        )
        self.pub = _FakePublisher()
        self.act = _FakeActivator(verdict="dry_run")

    def tearDown(self):
        if self._orig is not None:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig

    def test_dry_run_happy_path(self):
        req = ap.AutopilotRequest(
            shop_url="s.myshopify.com",
            api_key="",   # optional in dry-run
            winner_sources=[
                _static_source(_winner_dict()),
            ],
            live=False,
        )
        pilot = ap.Autopilot(
            publisher_bundle=self.pub,
            campaign_activator=self.act,
        )
        run = pilot.run(req)
        self.assertTrue(run.dry_run)
        self.assertEqual(len(run.launches), 1)
        self.assertEqual(run.successful_launches, 1)
        launch = run.launches[0]
        self.assertEqual(launch.publish_verdict, "dry_run")
        self.assertEqual(
            launch.activate_verdict, "dry_run",
        )

    def test_honors_max_launches(self):
        req = ap.AutopilotRequest(
            shop_url="s.myshopify.com",
            api_key="",
            winner_sources=[
                _static_source(*[
                    _winner_dict(
                        external_id=f"w{i}",
                        title=f"Winner {i}",
                    )
                    for i in range(5)
                ]),
            ],
            max_launches=2,
            live=False,
        )
        pilot = ap.Autopilot(
            publisher_bundle=self.pub,
            campaign_activator=self.act,
        )
        run = pilot.run(req)
        self.assertEqual(len(run.launches), 2)


class TestLivePath(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get(
            "SHOPAI_ENABLE_LIVE_EXECUTION",
        )
        os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"

    def tearDown(self):
        if self._orig is None:
            os.environ.pop(
                "SHOPAI_ENABLE_LIVE_EXECUTION", None,
            )
        else:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig

    def test_live_happy_path(self):
        pub = _FakePublisher(ok=True)
        act = _FakeActivator(verdict="activated")
        req = ap.AutopilotRequest(
            shop_url="s.myshopify.com",
            api_key="tok",
            winner_sources=[
                _static_source(_winner_dict()),
            ],
            live=True,
        )
        pilot = ap.Autopilot(
            publisher_bundle=pub,
            campaign_activator=act,
        )
        run = pilot.run(req)
        self.assertFalse(run.dry_run)
        self.assertEqual(run.successful_launches, 1)
        launch = run.launches[0]
        self.assertEqual(launch.publish_verdict, "ok")
        self.assertEqual(
            launch.activate_verdict, "activated",
        )


class TestSkipActivate(unittest.TestCase):
    def test_auto_activate_false_skips(self):
        pub = _FakePublisher(ok=True)
        act = _FakeActivator(verdict="activated")
        req = ap.AutopilotRequest(
            shop_url="s.myshopify.com",
            api_key="tok",
            winner_sources=[
                _static_source(_winner_dict()),
            ],
            auto_activate=False,
            live=False,
        )
        pilot = ap.Autopilot(
            publisher_bundle=pub,
            campaign_activator=act,
        )
        run = pilot.run(req)
        self.assertEqual(
            run.launches[0].activate_verdict, "skipped",
        )
        # Activator never called
        self.assertEqual(act.calls, [])


class TestPublishFailures(unittest.TestCase):
    def test_publish_failure_skips_activate(self):
        pub = _FakePublisher(ok=False)
        act = _FakeActivator()
        req = ap.AutopilotRequest(
            shop_url="s.myshopify.com",
            api_key="tok",
            winner_sources=[
                _static_source(_winner_dict()),
            ],
            live=False,
        )
        pilot = ap.Autopilot(
            publisher_bundle=pub,
            campaign_activator=act,
        )
        run = pilot.run(req)
        launch = run.launches[0]
        self.assertEqual(launch.publish_verdict, "dry_run")
        # Publisher returned ok=False but dry_run=True means
        # verdict is 'dry_run'. Activate is skipped when
        # campaign_id is empty. The fake returned no campaign.
        # (successful_launches counts launches where both
        # publish AND activate are dry_run or ok.)
        # For an "error" publish verdict we want to test the
        # error path; flip live=True to exercise that.

    def test_publish_error_when_live(self):
        os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
        try:
            pub = _FakePublisher(ok=False)
            act = _FakeActivator()
            req = ap.AutopilotRequest(
                shop_url="s.myshopify.com",
                api_key="tok",
                winner_sources=[
                    _static_source(_winner_dict()),
                ],
                live=True,
            )
            pilot = ap.Autopilot(
                publisher_bundle=pub,
                campaign_activator=act,
            )
            run = pilot.run(req)
            self.assertEqual(
                run.launches[0].publish_verdict, "error",
            )
            self.assertEqual(
                run.launches[0].activate_verdict,
                "skipped",
            )
            self.assertEqual(act.calls, [])
        finally:
            os.environ.pop(
                "SHOPAI_ENABLE_LIVE_EXECUTION", None,
            )


class TestActivateBlocked(unittest.TestCase):
    def test_blocked_activation_recorded(self):
        os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
        try:
            pub = _FakePublisher(ok=True)
            act = _FakeActivator(verdict="blocked")
            req = ap.AutopilotRequest(
                shop_url="s.myshopify.com",
                api_key="tok",
                winner_sources=[
                    _static_source(_winner_dict()),
                ],
                live=True,
            )
            pilot = ap.Autopilot(
                publisher_bundle=pub,
                campaign_activator=act,
            )
            run = pilot.run(req)
            launch = run.launches[0]
            self.assertEqual(
                launch.activate_verdict, "blocked",
            )
            self.assertIn(
                "fake block", launch.block_reason,
            )
        finally:
            os.environ.pop(
                "SHOPAI_ENABLE_LIVE_EXECUTION", None,
            )


class TestIntegrationWithManualSeed(unittest.TestCase):
    def test_manual_seed_fed_into_pipeline(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            seeds = Path(tmp.name) / "seeds.json"
            seeds.write_text(json.dumps([
                {
                    "title": "Owner Pinned Winner",
                    "price": 40, "cost": 10,
                    "daily_sales": 30,
                    "saturation_score": 0.2,
                    "external_id": "pin-1",
                },
            ]))
            pub = _FakePublisher(ok=True)
            act = _FakeActivator(verdict="dry_run")
            req = ap.AutopilotRequest(
                shop_url="s.myshopify.com",
                api_key="",
                winner_sources=[
                    ManualSeedSource(seeds),
                ],
                live=False,
            )
            pilot = ap.Autopilot(
                publisher_bundle=pub,
                campaign_activator=act,
            )
            run = pilot.run(req)
            self.assertEqual(len(run.launches), 1)
            self.assertEqual(
                run.launches[0].winner_title,
                "Owner Pinned Winner",
            )
        finally:
            tmp.cleanup()


class TestQueries(unittest.TestCase):
    def test_recent_and_stats(self):
        pub = _FakePublisher()
        act = _FakeActivator(verdict="dry_run")
        pilot = ap.Autopilot(
            publisher_bundle=pub,
            campaign_activator=act,
        )
        req = ap.AutopilotRequest(
            shop_url="s.myshopify.com",
            api_key="",
            winner_sources=[
                _static_source(_winner_dict()),
            ],
            live=False,
        )
        pilot.run(req)
        pilot.run(req)
        self.assertEqual(len(pilot.recent()), 2)
        s = pilot.stats()
        self.assertEqual(s["runs"], 2)
        self.assertEqual(s["total_launches"], 2)

    def test_reset(self):
        pilot = ap.Autopilot(
            publisher_bundle=_FakePublisher(),
            campaign_activator=_FakeActivator(
                verdict="dry_run",
            ),
        )
        req = ap.AutopilotRequest(
            shop_url="s.myshopify.com",
            api_key="",
            winner_sources=[
                _static_source(_winner_dict()),
            ],
            live=False,
        )
        pilot.run(req)
        self.assertEqual(pilot.reset(), 1)


class TestDict(unittest.TestCase):
    def test_launch_serialises(self):
        launch = ap.AutopilotLaunch(
            winner_title="x", decision_id="y",
            publish_verdict="dry_run",
            activate_verdict="dry_run",
        )
        d = launch.as_dict()
        self.assertEqual(d["winner_title"], "x")

    def test_run_serialises(self):
        pilot = ap.Autopilot(
            publisher_bundle=_FakePublisher(),
            campaign_activator=_FakeActivator(
                verdict="dry_run",
            ),
        )
        req = ap.AutopilotRequest(
            shop_url="s.myshopify.com",
            api_key="",
            winner_sources=[
                _static_source(_winner_dict()),
            ],
            live=False,
        )
        run = pilot.run(req)
        d = run.as_dict()
        self.assertIn("launches", d)
        self.assertIn("successful_launches", d)


if __name__ == "__main__":
    unittest.main()
