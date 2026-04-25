"""BrainStateSynthesizer Wave A-B-D integration tests.

Locks in that ``snapshot()`` populates the three new rollup
fields (agentic_enabled_channels, moby_win_rate,
fal_weekly_spend_usd) and that failing sources degrade
gracefully into notes rather than crashing the snapshot.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.brain.brain_state_synthesizer import (
    BrainState,
    BrainStateSynthesizer,
)


def _fresh_synthesizer():
    return BrainStateSynthesizer(
        crisis_responder=MagicMock(
            detect_state=MagicMock(return_value=MagicMock(
                level="green", halted=False,
            )),
        ),
        risk_tripwire=MagicMock(
            utilisation=MagicMock(return_value=0.2),
            remaining_budget=MagicMock(
                return_value=100.0,
            ),
        ),
        rulebook=MagicMock(
            stats=MagicMock(return_value={
                "proposed": 0, "active": 0,
                "demoted": 0, "deleted": 0,
            }),
        ),
        memory_consolidator=MagicMock(
            stats=MagicMock(return_value={
                "episodes": 0, "concepts": 0,
                "procedures": 0, "cold_archive": 0,
            }),
        ),
        trust_calibrator=MagicMock(
            ranked=MagicMock(return_value=[]),
        ),
        rationale_ledger=MagicMock(
            stats=MagicMock(return_value={
                "total_rationales": 0,
            }),
        ),
    )


class TestAgenticFieldPopulation(unittest.TestCase):
    def test_enabled_channels_collected(self):
        s1 = MagicMock(channel="chatgpt", enabled=True)
        s2 = MagicMock(channel="perplexity", enabled=False)
        s3 = MagicMock(channel="copilot", enabled=True)
        fake_bridge = MagicMock()
        fake_bridge.status.return_value = [s1, s2, s3]

        with patch(
            "core.bridge.agentic_storefront"
            ".get_agentic_bridge",
            return_value=fake_bridge,
        ):
            snap = _fresh_synthesizer().snapshot()
        self.assertEqual(
            snap.agentic_enabled_channels,
            ("chatgpt", "copilot"),
        )

    def test_bridge_failure_becomes_note(self):
        with patch(
            "core.bridge.agentic_storefront"
            ".get_agentic_bridge",
            side_effect=RuntimeError("bridge down"),
        ):
            snap = _fresh_synthesizer().snapshot()
        self.assertEqual(
            snap.agentic_enabled_channels, (),
        )
        self.assertTrue(
            any(
                "agentic bridge" in n
                for n in snap.notes
            ),
        )


class TestMobyFieldPopulation(unittest.TestCase):
    def test_win_rate_rolled_up(self):
        fake = MagicMock()
        fake.win_rate.return_value = {
            "total_resolved": 5,
            "shopai_only": 3,
            "moby_only": 1,
            "both_correct": 1,
            "both_wrong": 0,
            "moby_win_rate": 0.4,
            "shopai_win_rate": 0.8,
        }
        with patch(
            "core.brain.moby_vote_comparator"
            ".get_moby_vote_comparator",
            return_value=fake,
        ):
            snap = _fresh_synthesizer().snapshot()
        self.assertEqual(
            snap.moby_win_rate["total_resolved"], 5,
        )
        self.assertAlmostEqual(
            snap.moby_win_rate["shopai_win_rate"], 0.8,
        )

    def test_comparator_failure_becomes_note(self):
        with patch(
            "core.brain.moby_vote_comparator"
            ".get_moby_vote_comparator",
            side_effect=RuntimeError("boom"),
        ):
            snap = _fresh_synthesizer().snapshot()
        self.assertEqual(snap.moby_win_rate, {})
        self.assertTrue(
            any("moby" in n for n in snap.notes),
        )


class TestFalFieldPopulation(unittest.TestCase):
    def test_spend_collected(self):
        fake_router = MagicMock()
        fake_router.stats.return_value = {
            "total_spend_usd": 12.34,
            "configured": True,
        }
        with patch(
            "core.adapters.fal.video_router"
            ".FalVideoRouter",
            return_value=fake_router,
        ):
            snap = _fresh_synthesizer().snapshot()
        self.assertAlmostEqual(
            snap.fal_weekly_spend_usd, 12.34,
        )

    def test_router_failure_becomes_note(self):
        with patch(
            "core.adapters.fal.video_router"
            ".FalVideoRouter",
            side_effect=RuntimeError("no db"),
        ):
            snap = _fresh_synthesizer().snapshot()
        self.assertEqual(snap.fal_weekly_spend_usd, 0.0)
        self.assertTrue(
            any("fal" in n for n in snap.notes),
        )


class TestAsDictIncludesNewFields(unittest.TestCase):
    def test_round_trip(self):
        snap = _fresh_synthesizer().snapshot()
        d = snap.as_dict()
        self.assertIn("agentic_enabled_channels", d)
        self.assertIn("moby_win_rate", d)
        self.assertIn("fal_weekly_spend_usd", d)
        # types round-trip correctly
        self.assertIsInstance(
            d["agentic_enabled_channels"], list,
        )
        self.assertIsInstance(d["moby_win_rate"], dict)
        self.assertIsInstance(
            d["fal_weekly_spend_usd"], float,
        )


class TestBackwardCompat(unittest.TestCase):
    def test_old_direct_construction_still_works(self):
        # Consumers that build BrainState themselves with only
        # the original kwargs shouldn't break.
        s = BrainState(
            ts=1.0, crisis_level="green", halted=False,
            tripwire_utilisation=0.0,
            tripwire_remaining_usd=100.0,
            rule_counts={}, memory_counts={},
            trust_top=(), rationale_total=0,
            priorities=(),
        )
        d = s.as_dict()
        # New fields default to empty / 0
        self.assertEqual(
            d["agentic_enabled_channels"], [],
        )
        self.assertEqual(d["moby_win_rate"], {})
        self.assertEqual(
            d["fal_weekly_spend_usd"], 0.0,
        )


if __name__ == "__main__":
    unittest.main()
