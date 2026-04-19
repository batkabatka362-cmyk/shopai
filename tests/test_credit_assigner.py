"""Credit assigner tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import credit_assigner as ca


class TestConfig(unittest.TestCase):
    def test_invalid_config_raises(self) -> None:
        with self.assertRaises(ValueError):
            ca.CreditAssigner(half_life_s=0)
        with self.assertRaises(ValueError):
            ca.CreditAssigner(claimed_boost=0.5)


class TestSingleDecision(unittest.TestCase):
    def test_single_decision_gets_full_credit(self) -> None:
        c = ca.CreditAssigner(half_life_s=86400, lookback_s=86400 * 7)
        c.note_decision(decision_id="d1", ts=1000.0)
        c.note_outcome(
            outcome_id="o1", kpi="revenue",
            value=100.0, ts=1100.0,
        )
        rep = c.credits_for("o1")
        self.assertAlmostEqual(rep.credits["d1"], 100.0)


class TestClaimedKpiBoost(unittest.TestCase):
    def test_claimer_beats_unclaimer(self) -> None:
        c = ca.CreditAssigner(
            half_life_s=86400, lookback_s=86400 * 7,
            claimed_boost=5.0,
        )
        c.note_decision(
            decision_id="claimer", ts=1000.0,
            claimed_kpis=["revenue"],
        )
        c.note_decision(
            decision_id="other", ts=1000.0,
            claimed_kpis=[],
        )
        c.note_outcome(
            outcome_id="o1", kpi="revenue",
            value=100.0, ts=1100.0,
        )
        rep = c.credits_for("o1")
        self.assertGreater(
            rep.credits["claimer"], rep.credits["other"],
        )


class TestTimeDecay(unittest.TestCase):
    def test_recent_beats_old(self) -> None:
        c = ca.CreditAssigner(
            half_life_s=100.0, lookback_s=1000.0,
        )
        c.note_decision(decision_id="old", ts=0.0)
        c.note_decision(decision_id="new", ts=500.0)
        c.note_outcome(
            outcome_id="o1", kpi="x", value=100.0, ts=500.0,
        )
        rep = c.credits_for("o1")
        self.assertGreater(rep.credits["new"], rep.credits["old"])

    def test_future_decision_zero_credit(self) -> None:
        c = ca.CreditAssigner()
        # Decision AFTER the outcome can't have caused it.
        c.note_decision(decision_id="future", ts=2000.0)
        c.note_outcome(
            outcome_id="o", kpi="x", value=100.0, ts=1000.0,
        )
        rep = c.credits_for("o")
        self.assertNotIn("future", rep.credits)

    def test_beyond_lookback_zero_credit(self) -> None:
        c = ca.CreditAssigner(lookback_s=100.0, half_life_s=50.0)
        c.note_decision(decision_id="ancient", ts=0.0)
        c.note_outcome(
            outcome_id="o", kpi="x", value=100.0, ts=500.0,
        )
        rep = c.credits_for("o")
        self.assertNotIn("ancient", rep.credits)


class TestNormalisation(unittest.TestCase):
    def test_credits_sum_to_outcome_value(self) -> None:
        c = ca.CreditAssigner(
            half_life_s=86400, lookback_s=86400 * 7,
        )
        for i, d in enumerate(["a", "b", "c"]):
            c.note_decision(decision_id=d, ts=1000.0 + i)
        c.note_outcome(
            outcome_id="o", kpi="x", value=120.0, ts=1100.0,
        )
        rep = c.credits_for("o")
        self.assertAlmostEqual(
            sum(rep.credits.values()), 120.0, places=4,
        )


class TestTotalCredit(unittest.TestCase):
    def test_total_across_outcomes(self) -> None:
        c = ca.CreditAssigner(
            half_life_s=86400, lookback_s=86400 * 7,
        )
        c.note_decision(decision_id="d1", ts=1000.0)
        c.note_outcome(
            outcome_id="o1", kpi="x", value=100.0, ts=1100.0,
        )
        c.note_outcome(
            outcome_id="o2", kpi="x", value=50.0, ts=1200.0,
        )
        self.assertAlmostEqual(c.total_credit("d1"), 150.0)


class TestTopDecisions(unittest.TestCase):
    def test_ranked_by_total(self) -> None:
        c = ca.CreditAssigner(
            half_life_s=86400, lookback_s=86400 * 7,
        )
        c.note_decision(
            decision_id="claimer", ts=1000.0,
            claimed_kpis=["revenue"],
        )
        c.note_decision(decision_id="other", ts=1000.0)
        c.note_outcome(
            outcome_id="o", kpi="revenue",
            value=100.0, ts=1100.0,
        )
        top = c.top_decisions(kpi="revenue")
        self.assertEqual(top[0][0], "claimer")

    def test_kpi_filter(self) -> None:
        c = ca.CreditAssigner(
            half_life_s=86400, lookback_s=86400 * 7,
        )
        c.note_decision(decision_id="d1", ts=1000.0)
        c.note_outcome(outcome_id="o1", kpi="a", value=5, ts=1100)
        c.note_outcome(outcome_id="o2", kpi="b", value=5, ts=1100)
        top_a = c.top_decisions(kpi="a")
        top_b = c.top_decisions(kpi="b")
        self.assertAlmostEqual(top_a[0][1], 5.0)
        self.assertAlmostEqual(top_b[0][1], 5.0)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "c.db"
        first = ca.CreditAssigner(db_path=path)
        first.note_decision(decision_id="d1", ts=1000.0)
        first.note_outcome(
            outcome_id="o1", kpi="x", value=5.0, ts=1100.0,
        )
        first.close()
        second = ca.CreditAssigner(db_path=path)
        rep = second.credits_for("o1")
        self.assertIn("d1", rep.credits)
        second.close()
        tmp.cleanup()


class TestPrune(unittest.TestCase):
    def test_prune_before_cutoff(self) -> None:
        c = ca.CreditAssigner()
        c.note_decision(decision_id="old", ts=0.0)
        c.note_decision(decision_id="new", ts=1_000_000.0)
        n = c.prune_before(500.0)
        self.assertEqual(n, 1)
        self.assertEqual(c.stats()["decisions"], 1)


class TestEmpty(unittest.TestCase):
    def test_unknown_outcome_empty_report(self) -> None:
        c = ca.CreditAssigner()
        rep = c.credits_for("nobody")
        self.assertEqual(rep.credits, {})

    def test_no_decisions_zero_credit(self) -> None:
        c = ca.CreditAssigner()
        c.note_outcome(
            outcome_id="o", kpi="x", value=10.0, ts=1.0,
        )
        rep = c.credits_for("o")
        self.assertEqual(rep.credits, {})

    def test_blank_kpi_raises(self) -> None:
        c = ca.CreditAssigner()
        with self.assertRaises(ValueError):
            c.note_outcome(kpi="", value=1.0)


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        c = ca.CreditAssigner()
        c.note_decision(decision_id="d", ts=1.0)
        c.note_outcome(
            outcome_id="o", kpi="x", value=5.0, ts=2.0,
        )
        d = c.credits_for("o").as_dict()
        self.assertIn("credits", d)
        self.assertIn("value", d)


if __name__ == "__main__":
    unittest.main()
