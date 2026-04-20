"""Tests for core.brain.brain_state_synthesizer — Track 9."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.brain.brain_state_synthesizer import (
    BrainState,
    BrainStateSynthesizer,
    PriorityItem,
    get_brain_state_synthesizer,
    reset_brain_state_synthesizer_for_tests,
)


def _crisis(level="green", halted=False, reason=""):
    c = MagicMock()
    state = MagicMock()
    state.level = level
    state.halted = halted
    state.reason = reason
    c.detect_state.return_value = state
    return c


def _tripwire(util=0.2, remaining=40.0):
    t = MagicMock()
    t.status.return_value = {
        "today": {
            "utilisation": util,
            "remaining_usd": remaining,
            "ad_spend_usd": 10.0,
        },
        "limits": {},
    }
    return t


def _rulebook(by_status=None):
    r = MagicMock()
    r.stats.return_value = {
        "by_status": by_status or {},
    }
    return r


def _consolidator(
    episodes=0, concepts=0, procedures=0,
    cold_archive=0,
):
    c = MagicMock()
    c.stats.return_value = {
        "episodes": episodes,
        "concepts": concepts,
        "procedures": procedures,
        "cold_archive": cold_archive,
    }
    return c


def _trust(ranked=None):
    t = MagicMock()
    t.ranked.return_value = list(ranked or [])
    return t


def _rationale(total=0):
    r = MagicMock()
    r.stats.return_value = {
        "total_rationales": total,
    }
    return r


def _synth(**deps):
    defaults = dict(
        crisis_responder=_crisis(),
        risk_tripwire=_tripwire(),
        rulebook=_rulebook(),
        memory_consolidator=_consolidator(),
        trust_calibrator=_trust(),
        rationale_ledger=_rationale(),
        now_fn=lambda: 1_000_000.0,
    )
    defaults.update(deps)
    return BrainStateSynthesizer(**defaults)


class TestSnapshot(unittest.TestCase):
    def test_green_idle_state(self):
        synth = _synth()
        state = synth.snapshot()
        self.assertEqual(state.crisis_level, "green")
        self.assertFalse(state.halted)
        # Empty rulebook + zero rationale → 1 info priority
        codes = [p.code for p in state.priorities]
        self.assertIn("rationale_empty", codes)

    def test_crisis_red_top_priority(self):
        synth = _synth(
            crisis_responder=_crisis(
                level="red", halted=True,
                reason="platform ban",
            ),
        )
        state = synth.snapshot()
        self.assertEqual(state.crisis_level, "red")
        self.assertTrue(state.halted)
        self.assertEqual(
            state.priorities[0].code, "crisis_red",
        )
        self.assertEqual(
            state.priorities[0].level, "critical",
        )

    def test_tripwire_high_warning(self):
        synth = _synth(
            risk_tripwire=_tripwire(util=0.9),
        )
        codes = [
            p.code for p in synth.snapshot().priorities
        ]
        self.assertIn("tripwire_high", codes)

    def test_tripwire_below_80_no_warning(self):
        synth = _synth(
            risk_tripwire=_tripwire(util=0.5),
        )
        codes = [
            p.code for p in synth.snapshot().priorities
        ]
        self.assertNotIn("tripwire_high", codes)

    def test_rules_unreviewed_warning(self):
        synth = _synth(
            rulebook=_rulebook(by_status={
                "proposed": 7, "active": 0,
            }),
        )
        codes = [
            p.code for p in synth.snapshot().priorities
        ]
        self.assertIn("rules_unreviewed", codes)

    def test_active_rule_suppresses_warning(self):
        synth = _synth(
            rulebook=_rulebook(by_status={
                "proposed": 7, "active": 1,
            }),
        )
        codes = [
            p.code for p in synth.snapshot().priorities
        ]
        self.assertNotIn("rules_unreviewed", codes)

    def test_memory_stalled_warning(self):
        synth = _synth(
            memory_consolidator=_consolidator(
                concepts=0, cold_archive=5,
            ),
        )
        codes = [
            p.code for p in synth.snapshot().priorities
        ]
        self.assertIn("memory_stalled", codes)

    def test_trust_weak_top_source(self):
        synth = _synth(
            trust_calibrator=_trust(
                ranked=[("bad", 0.2), ("ok", 0.15)],
            ),
        )
        codes = [
            p.code for p in synth.snapshot().priorities
        ]
        self.assertIn("trust_weak", codes)

    def test_rationale_non_zero_suppresses_info(self):
        synth = _synth(
            rationale_ledger=_rationale(total=7),
        )
        codes = [
            p.code for p in synth.snapshot().priorities
        ]
        self.assertNotIn("rationale_empty", codes)

    def test_priority_ordering_critical_first(self):
        synth = _synth(
            crisis_responder=_crisis(
                level="red", halted=True,
            ),
            risk_tripwire=_tripwire(util=0.95),
            rulebook=_rulebook(by_status={
                "proposed": 10, "active": 0,
            }),
        )
        levels = [
            p.level for p in synth.snapshot().priorities
        ]
        self.assertEqual(levels[0], "critical")


class TestSignalCollectionResilience(unittest.TestCase):
    def test_crisis_exception_captured_in_notes(self):
        crisis = MagicMock()
        crisis.detect_state.side_effect = RuntimeError(
            "no db",
        )
        synth = _synth(crisis_responder=crisis)
        state = synth.snapshot()
        self.assertEqual(state.crisis_level, "unknown")
        self.assertTrue(
            any(
                "crisis read" in n
                for n in state.notes
            ),
        )

    def test_tripwire_exception_does_not_halt(self):
        tw = MagicMock()
        tw.status.side_effect = RuntimeError("boom")
        synth = _synth(risk_tripwire=tw)
        state = synth.snapshot()
        self.assertEqual(state.tripwire_utilisation, 0.0)
        self.assertTrue(
            any("tripwire" in n for n in state.notes),
        )

    def test_all_nulls_still_returns_state(self):
        # No deps at all — synth falls back to lazy loaders
        # which all fail, but snapshot should still return.
        synth = BrainStateSynthesizer(
            crisis_responder=MagicMock(
                detect_state=MagicMock(
                    side_effect=RuntimeError("x"),
                ),
            ),
            risk_tripwire=MagicMock(
                status=MagicMock(
                    side_effect=RuntimeError("x"),
                ),
            ),
            rulebook=MagicMock(
                stats=MagicMock(
                    side_effect=RuntimeError("x"),
                ),
            ),
            memory_consolidator=MagicMock(
                stats=MagicMock(
                    side_effect=RuntimeError("x"),
                ),
            ),
            trust_calibrator=MagicMock(
                ranked=MagicMock(
                    side_effect=RuntimeError("x"),
                ),
            ),
            rationale_ledger=MagicMock(
                stats=MagicMock(
                    side_effect=RuntimeError("x"),
                ),
            ),
        )
        state = synth.snapshot()
        self.assertIsInstance(state, BrainState)


class TestSingleton(unittest.TestCase):
    def test_singleton(self):
        reset_brain_state_synthesizer_for_tests()
        try:
            a = get_brain_state_synthesizer()
            b = get_brain_state_synthesizer()
            self.assertIs(a, b)
        finally:
            reset_brain_state_synthesizer_for_tests()


class TestDict(unittest.TestCase):
    def test_priority_dict(self):
        p = PriorityItem(
            level="info", code="c", message="m",
            detail="d",
        )
        self.assertEqual(
            p.as_dict()["code"], "c",
        )

    def test_state_dict(self):
        synth = _synth()
        state = synth.snapshot()
        d = state.as_dict()
        self.assertIn("priorities", d)
        self.assertIn("crisis_level", d)


if __name__ == "__main__":
    unittest.main()
