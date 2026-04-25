"""Regret minimizer tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import regret_minimizer as rm


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = rm.RegretMinimizer(Path(self._tmp.name) / "r.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_record_computes_regret(self) -> None:
        e = self.m.record(
            signature="niche=audio",
            chosen_action="kill",
            realised=0.5,
            counterfactual=2.0,
        )
        self.assertAlmostEqual(e.regret, 1.5)

    def test_blank_signature_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record("", "kill", 1.0, 2.0)

    def test_blank_action_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record("x", "", 1.0, 2.0)


class TestAdvise(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = rm.RegretMinimizer(Path(self._tmp.name) / "r.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_empty_signature_neutral_advice(self) -> None:
        adv = self.m.advise("unknown")
        self.assertEqual(adv.biases, {})
        self.assertEqual(adv.entries, 0)

    def test_lower_regret_higher_bias(self) -> None:
        sig = "niche=audio"
        # kill produced 3 units of regret across 3 cycles
        for _ in range(3):
            self.m.record(sig, "kill", realised=0.5, counterfactual=1.5)
        # scale produced almost no regret
        for _ in range(3):
            self.m.record(sig, "scale", realised=2.0, counterfactual=2.1)
        adv = self.m.advise(sig)
        self.assertGreater(adv.biases["scale"], adv.biases["kill"])
        self.assertEqual(adv.top_action(), "scale")

    def test_actions_default_included(self) -> None:
        sig = "x"
        self.m.record(sig, "kill", realised=1.0, counterfactual=1.5)
        adv = self.m.advise(sig, actions=["kill", "scale", "wait"])
        self.assertIn("scale", adv.biases)
        self.assertIn("wait", adv.biases)


class TestTopRegretted(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = rm.RegretMinimizer(Path(self._tmp.name) / "r.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_top_ordered_by_cumulative_regret(self) -> None:
        self.m.record("sig_hot", "a", realised=0.5, counterfactual=3.0)
        self.m.record("sig_hot", "a", realised=0.5, counterfactual=3.0)
        self.m.record("sig_cool", "a", realised=1.5, counterfactual=2.0)
        top = self.m.top_regretted()
        self.assertEqual(top[0][0], "sig_hot")


class TestSummary(unittest.TestCase):
    def test_summary_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RegretMinimizer(Path(tmp.name) / "r.db")
        m.record("a", "kill", realised=1.0, counterfactual=2.0)
        m.record("b", "scale", realised=2.0, counterfactual=2.0)
        s = m.summary()
        self.assertEqual(s["total_entries"], 2)
        self.assertAlmostEqual(s["cumulative_regret"], 1.0)
        self.assertAlmostEqual(s["avg_regret"], 0.5)
        tmp.cleanup()


class TestEntriesFor(unittest.TestCase):
    def test_entries_for_signature(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RegretMinimizer(Path(tmp.name) / "r.db")
        for _ in range(5):
            m.record("audio", "kill", realised=0.5, counterfactual=1.5)
        entries = m.entries_for("audio", limit=3)
        self.assertEqual(len(entries), 3)
        self.assertTrue(
            all(e.signature == "audio" for e in entries),
        )
        tmp.cleanup()


class TestBiasDistribution(unittest.TestCase):
    def test_biases_sum_to_one(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RegretMinimizer(Path(tmp.name) / "r.db")
        m.record("x", "a", realised=1.0, counterfactual=2.0)
        m.record("x", "b", realised=2.0, counterfactual=2.0)
        adv = m.advise("x")
        self.assertAlmostEqual(sum(adv.biases.values()), 1.0, places=3)
        tmp.cleanup()


class TestSingleton(unittest.TestCase):
    def test_minimizer_returns_same_instance(self) -> None:
        self.assertIs(rm.minimizer(), rm.minimizer())


if __name__ == "__main__":
    unittest.main()
