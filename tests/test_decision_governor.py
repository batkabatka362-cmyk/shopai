"""Decision governor tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import decision_governor as dg
from core.brain import dual_process as dp
from core.brain import safety_envelope as sf
from core.brain import policy_library as pl


def _fast(x):
    return {"kind": "fast_action", **x}


def _slow(x):
    return {"kind": "slow_action", **x}


class TestGovernorHappy(unittest.TestCase):
    def setUp(self) -> None:
        self.arbiter = dp.DualProcessArbiter(_fast, _slow)

    def test_allows_normal_action(self) -> None:
        gov = dg.DecisionGovernor(
            arbiter=self.arbiter,
            envelope_builder=lambda ctx: sf.Envelope(),
        )
        d = gov.govern(
            context={"niche": "audio"},
            candidate_action={"x": 1},
            stakes=0.1, confidence=0.9,
        )
        self.assertEqual(d.status, "allowed")
        self.assertEqual(d.route, "system1")
        self.assertIsNotNone(d.action)

    def test_route_escalates_on_high_stakes(self) -> None:
        gov = dg.DecisionGovernor(
            arbiter=self.arbiter,
            envelope_builder=lambda ctx: sf.Envelope(),
        )
        d = gov.govern(
            context={},
            candidate_action={"x": 1},
            stakes=0.9, confidence=0.5,
        )
        self.assertEqual(d.route, "system2")


class TestEnvelopeClamp(unittest.TestCase):
    def test_clamps_over_cap(self) -> None:
        arbiter = dp.DualProcessArbiter(lambda x: x, lambda x: x)
        envelope = sf.Envelope(
            numeric_ranges={"daily_spend_usd": (0, 100)},
        )
        gov = dg.DecisionGovernor(
            arbiter=arbiter,
            envelope_builder=lambda ctx: envelope,
        )
        d = gov.govern(
            context={},
            candidate_action={"daily_spend_usd": 9999},
            stakes=0.2, confidence=0.8,
        )
        self.assertEqual(d.status, "clamped")
        self.assertEqual(d.action["daily_spend_usd"], 100)


class TestEthicsBlock(unittest.TestCase):
    def test_hard_block_returns_blocked(self) -> None:
        arbiter = dp.DualProcessArbiter(lambda x: x, lambda x: x)
        gov = dg.DecisionGovernor(
            arbiter=arbiter,
            envelope_builder=lambda ctx: sf.Envelope(),
        )
        d = gov.govern(
            context={},
            candidate_action={
                "kind": "set_price",
                "price": 29.0,
                "compare_at_price": 299.0,
                "verified_historical_max_price": 50.0,
            },
            stakes=0.1, confidence=0.9,
        )
        self.assertEqual(d.status, "blocked")
        self.assertIsNone(d.action)
        rules = [v["rule"] for v in d.ethics_violations]
        self.assertIn("no_deceptive_price_anchor", rules)

    def test_soft_violation_still_allowed(self) -> None:
        arbiter = dp.DualProcessArbiter(lambda x: x, lambda x: x)
        gov = dg.DecisionGovernor(
            arbiter=arbiter,
            envelope_builder=lambda ctx: sf.Envelope(),
        )
        d = gov.govern(
            context={},
            candidate_action={
                "kind": "send_email",
                "recipient": "alice",
                "emails_in_last_24h": 3,
            },
            stakes=0.1, confidence=0.9,
        )
        # Soft block still flows through
        self.assertIn(d.status, ("allowed", "clamped"))
        self.assertIsNotNone(d.action)


class TestPolicyMatch(unittest.TestCase):
    def test_policy_included_in_trace(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        lib = pl.PolicyLibrary(Path(tmp.name) / "p.db")
        lib.register(
            name="audio_kill",
            description="",
            applicability={"niche": "audio"},
            action_template={},
        )
        arbiter = dp.DualProcessArbiter(lambda x: x, lambda x: x)
        gov = dg.DecisionGovernor(
            arbiter=arbiter,
            policy_library=lib,
            envelope_builder=lambda ctx: sf.Envelope(),
        )
        d = gov.govern(
            context={"niche": "audio"},
            candidate_action={"x": 1},
            stakes=0.2, confidence=0.8,
        )
        self.assertEqual(len(d.policies), 1)
        self.assertEqual(d.policies[0].policy.name, "audio_kill")
        tmp.cleanup()


class TestTrace(unittest.TestCase):
    def test_trace_every_stage(self) -> None:
        arbiter = dp.DualProcessArbiter(lambda x: x, lambda x: x)
        gov = dg.DecisionGovernor(
            arbiter=arbiter,
            envelope_builder=lambda ctx: sf.Envelope(),
        )
        d = gov.govern(
            context={},
            candidate_action={"x": 1},
            stakes=0.1, confidence=0.9,
        )
        stages = [t.stage for t in d.trace]
        for expected in (
            "envelope", "ethics_pre", "dual_process", "ethics_post",
        ):
            self.assertIn(expected, stages)

    def test_rationale_mentions_route(self) -> None:
        arbiter = dp.DualProcessArbiter(lambda x: x, lambda x: x)
        gov = dg.DecisionGovernor(
            arbiter=arbiter,
            envelope_builder=lambda ctx: sf.Envelope(),
        )
        d = gov.govern(
            context={}, candidate_action={"x": 1},
            stakes=0.1, confidence=0.9,
        )
        self.assertIn("route=", d.rationale)


class TestPostCheckBlocks(unittest.TestCase):
    def test_slow_path_introducing_violation_caught(self) -> None:
        # slow path returns an action that violates ethics
        def slow(x):
            return {
                "kind": "set_price",
                "price": 29.0,
                "compare_at_price": 999.0,
                "verified_historical_max_price": 50.0,
            }
        arbiter = dp.DualProcessArbiter(lambda x: x, slow)
        gov = dg.DecisionGovernor(
            arbiter=arbiter,
            envelope_builder=lambda ctx: sf.Envelope(),
        )
        d = gov.govern(
            context={}, candidate_action={"ok": 1},
            stakes=0.9, confidence=0.5,   # forces system2
        )
        self.assertEqual(d.status, "blocked")
        stages = [t.stage for t in d.trace]
        self.assertIn("ethics_post", stages)


if __name__ == "__main__":
    unittest.main()
