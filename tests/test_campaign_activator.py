"""Campaign activator tests."""
from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock

from execution.launch import campaign_activator as ca


# ── Fakes ───────────────────────────────────────────────────


class _FakeAds:
    def __init__(self, success=True):
        self._success = success
        self.calls: list[tuple[Any, dict]] = []

    def execute(self, capability, params):
        from core.adapters.base import AdapterResult
        from core.adapters.errors import AdapterError
        self.calls.append((capability, params))
        if self._success:
            return AdapterResult.success(
                adapter="fake_ads",
                capability=capability.value,
                data={
                    "campaign_id": params.get("campaign_id"),
                    "status": "ACTIVE",
                },
                raw={},
            )
        return AdapterResult.failure(
            adapter="fake_ads",
            capability=capability.value,
            error=AdapterError("fake_ads", "denied"),
            raw={},
        )


class _FakeReadiness:
    def __init__(self, verdict="go", reason="looks ready"):
        self._verdict = verdict
        self._reason = reason

    def check(self, inp):
        from core.brain.readiness_gate import ReadinessDecision
        import time
        return ReadinessDecision(
            verdict=self._verdict,
            score=0.8,
            reason=self._reason,
            recommended_wait_s=0.0,
            ts=time.time(),
        )


class _FakeConstraints:
    def __init__(self, any_severe=False, n_alerts=0):
        self._severe = any_severe
        self._n = n_alerts

    def evaluate(self, *, action, context):
        from core.brain.behavioral_constraint_registry import (
            ConstraintAlert, EvaluationResult,
        )
        import time
        alerts = []
        if self._n > 0:
            severity = "severe" if self._severe else "warn"
            alerts = [
                ConstraintAlert(
                    id=f"a{i}", constraint_id=f"c{i}",
                    action_kind=str(action.get("kind")),
                    severity=severity,
                    note=f"fake alert {i}",
                    ts=time.time(),
                )
                for i in range(self._n)
            ]
        return EvaluationResult(
            alerts=alerts, any_severe=self._severe,
        )


class _FakeOutcomes:
    def __init__(self):
        self.recorded: list[Any] = []

    def record(self, event):
        self.recorded.append(event)
        return MagicMock(event_id="e1")


class _FakeRationale:
    def __init__(self):
        self.started: list[Any] = []
        self.added: list[Any] = []
        self.committed: list[str] = []

    def start(self, *, decision_id, summary):
        self.started.append((decision_id, summary))
        return MagicMock()

    def add(self, decision_id, **kw):
        self.added.append((decision_id, kw))
        return MagicMock()

    def commit(self, decision_id):
        self.committed.append(decision_id)
        return MagicMock()


def _activator(**overrides):
    defaults = dict(
        ad_adapter=_FakeAds(),
        readiness_checker=_FakeReadiness(),
        constraint_registry=_FakeConstraints(),
        outcome_recorder=_FakeOutcomes(),
        rationale_builder=_FakeRationale(),
    )
    defaults.update(overrides)
    return ca.CampaignActivator(**defaults)


def _req(**kw):
    defaults = dict(
        campaign_id="camp_abc",
        daily_budget_usd=20.0,
        auto_approve=True,
    )
    defaults.update(kw)
    return ca.ActivateRequest(**defaults)


# ── Tests ───────────────────────────────────────────────────


class TestRequest(unittest.TestCase):
    def test_blank_campaign_raises(self):
        with self.assertRaises(ValueError):
            ca.ActivateRequest(campaign_id="")

    def test_bad_budget_raises(self):
        with self.assertRaises(ValueError):
            ca.ActivateRequest(
                campaign_id="c", daily_budget_usd=-5,
            )

    def test_bad_probability_raises(self):
        with self.assertRaises(ValueError):
            ca.ActivateRequest(
                campaign_id="c",
                evidence_probability=2.0,
            )


class TestConfig(unittest.TestCase):
    def test_bad_max_budget_raises(self):
        with self.assertRaises(ValueError):
            ca.CampaignActivator(
                max_daily_budget_usd=0,
            )


class TestDryRun(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.pop(
            "SHOPAI_ENABLE_LIVE_EXECUTION", None,
        )
        self.ads = _FakeAds()
        self.act = _activator(ad_adapter=self.ads)

    def tearDown(self):
        if self._orig is not None:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig

    def test_dry_run_verdict(self):
        r = self.act.activate(_req(live=False))
        self.assertEqual(r.verdict, "dry_run")
        self.assertTrue(r.dry_run)
        # Ads.execute never called in dry mode
        self.assertEqual(self.ads.calls, [])

    def test_live_flag_alone_insufficient(self):
        """ActivateRequest.live=True without env flag still
        produces dry_run — double-gate per CLAUDE.md §4b/G."""
        r = self.act.activate(_req(live=True))
        self.assertTrue(r.dry_run)


class TestLivePath(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get(
            "SHOPAI_ENABLE_LIVE_EXECUTION",
        )
        os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
        self.ads = _FakeAds()
        self.outcomes = _FakeOutcomes()
        self.rationale = _FakeRationale()
        self.act = _activator(
            ad_adapter=self.ads,
            outcome_recorder=self.outcomes,
            rationale_builder=self.rationale,
        )

    def tearDown(self):
        if self._orig is None:
            os.environ.pop(
                "SHOPAI_ENABLE_LIVE_EXECUTION", None,
            )
        else:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig

    def test_happy_path(self):
        r = self.act.activate(
            _req(live=True, auto_approve=True),
        )
        self.assertEqual(r.verdict, "activated")
        self.assertFalse(r.dry_run)
        self.assertTrue(r.activated)
        # Meta Ads got the resume call
        self.assertEqual(len(self.ads.calls), 1)
        capability, params = self.ads.calls[0]
        self.assertEqual(params["campaign_id"], "camp_abc")
        # Outcome recorded
        self.assertEqual(len(self.outcomes.recorded), 1)
        self.assertEqual(
            self.outcomes.recorded[0].kind,
            "campaign_activate",
        )
        # Rationale committed
        self.assertEqual(len(self.rationale.committed), 1)

    def test_owner_hold_when_not_auto_approved(self):
        r = self.act.activate(
            _req(live=True, auto_approve=False),
        )
        self.assertEqual(r.verdict, "pending")
        self.assertFalse(r.dry_run)
        # Ads.execute never called
        self.assertEqual(self.ads.calls, [])
        self.assertIn(
            "approval required", r.pending_reason,
        )


class TestBlockers(unittest.TestCase):
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

    def test_preflight_over_budget_blocks(self):
        act = _activator(
            max_daily_budget_usd=50.0,
        )
        r = act.activate(
            _req(
                live=True, auto_approve=True,
                daily_budget_usd=200.0,
            ),
        )
        self.assertEqual(r.verdict, "blocked")
        self.assertIn("cap", r.block_reason)

    def test_readiness_stand_down_blocks(self):
        ads = _FakeAds()
        act = _activator(
            ad_adapter=ads,
            readiness_checker=_FakeReadiness(
                verdict="stand_down", reason="too uncertain",
            ),
        )
        r = act.activate(
            _req(live=True, auto_approve=True),
        )
        self.assertEqual(r.verdict, "blocked")
        self.assertIn("stand_down", r.block_reason)
        self.assertEqual(ads.calls, [])

    def test_constraints_severe_blocks(self):
        ads = _FakeAds()
        act = _activator(
            ad_adapter=ads,
            constraint_registry=_FakeConstraints(
                any_severe=True, n_alerts=1,
            ),
        )
        r = act.activate(
            _req(live=True, auto_approve=True),
        )
        self.assertEqual(r.verdict, "blocked")
        self.assertIn("severe", r.block_reason)
        self.assertEqual(ads.calls, [])

    def test_constraints_advisory_passes(self):
        ads = _FakeAds()
        act = _activator(
            ad_adapter=ads,
            constraint_registry=_FakeConstraints(
                any_severe=False, n_alerts=2,
            ),
        )
        r = act.activate(
            _req(live=True, auto_approve=True),
        )
        self.assertEqual(r.verdict, "activated")
        self.assertEqual(len(ads.calls), 1)

    def test_ad_failure_blocks(self):
        ads = _FakeAds(success=False)
        act = _activator(
            ad_adapter=ads,
        )
        r = act.activate(
            _req(live=True, auto_approve=True),
        )
        self.assertEqual(r.verdict, "blocked")
        self.assertIn("denied", r.block_reason)


class TestReadinessAdvisory(unittest.TestCase):
    """``gather`` and ``warm_up`` must NOT block — they're advisory."""

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

    def test_gather_verdict_allows_activation(self):
        act = _activator(
            readiness_checker=_FakeReadiness(
                verdict="gather", reason="need more data",
            ),
        )
        r = act.activate(
            _req(live=True, auto_approve=True),
        )
        self.assertEqual(r.verdict, "activated")


class TestStats(unittest.TestCase):
    def test_stats_tracks_verdicts(self):
        act = _activator()
        act.activate(_req())  # dry_run
        act.activate(_req())
        s = act.stats()
        self.assertEqual(s["activations"], 2)
        self.assertEqual(s["by_verdict"]["dry_run"], 2)

    def test_recent(self):
        act = _activator()
        act.activate(_req())
        self.assertEqual(len(act.recent()), 1)

    def test_reset(self):
        act = _activator()
        act.activate(_req())
        self.assertEqual(act.reset(), 1)


class TestDict(unittest.TestCase):
    def test_step_serialises(self):
        s = ca.StepLog(name="x", status="ok", note="y")
        self.assertEqual(s.as_dict()["name"], "x")

    def test_result_serialises(self):
        act = _activator()
        r = act.activate(_req())
        d = r.as_dict()
        self.assertIn("verdict", d)
        self.assertIn("steps", d)


if __name__ == "__main__":
    unittest.main()
