"""Skill registry — posterior math + CRUD + composite confidence."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import skills as sk


class TestPosterior(unittest.TestCase):
    def test_confidence_starts_at_half(self) -> None:
        # Beta(1, 1) mean = 0.5
        s = sk.Skill(name="x")
        self.assertAlmostEqual(s.confidence, 0.5)

    def test_wins_push_confidence_up(self) -> None:
        s = sk.Skill(name="x", alpha=9, beta=1)
        self.assertAlmostEqual(s.confidence, 0.9)
        self.assertLess(s.uncertainty, 0.2)

    def test_losses_push_confidence_down(self) -> None:
        s = sk.Skill(name="x", alpha=1, beta=9)
        self.assertAlmostEqual(s.confidence, 0.1)


class TestRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.reg = sk.SkillRegistry(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_define_idempotent(self) -> None:
        s1 = self.reg.define("scrape.alibaba")
        s2 = self.reg.define("scrape.alibaba")
        self.assertEqual(s1.name, s2.name)
        self.assertEqual(self.reg.list_all()[0].name, "scrape.alibaba")

    def test_record_updates_counts_and_posterior(self) -> None:
        self.reg.define("x")
        s = self.reg.record("x", success=True)
        self.assertEqual(s.uses, 1)
        self.assertEqual(s.wins, 1)
        self.assertGreater(s.confidence, 0.5)

    def test_record_failure_increases_beta(self) -> None:
        self.reg.define("x")
        self.reg.record("x", success=False)
        s = self.reg.get("x")
        self.assertEqual(s.uses, 1)
        self.assertEqual(s.wins, 0)
        self.assertLess(s.confidence, 0.5)

    def test_record_auto_defines_unknown(self) -> None:
        self.reg.record("auto.new", success=True)
        s = self.reg.get("auto.new")
        self.assertIsNotNone(s)
        self.assertEqual(s.uses, 1)

    def test_list_all_filters_by_confidence(self) -> None:
        self.reg.define("good")
        self.reg.define("bad")
        for _ in range(5):
            self.reg.record("good", success=True)
        for _ in range(5):
            self.reg.record("bad", success=False)
        hi = self.reg.list_all(min_confidence=0.6)
        self.assertEqual(len(hi), 1)
        self.assertEqual(hi[0].name, "good")

    def test_composite_confidence_is_min_of_prereqs(self) -> None:
        self.reg.define("atom.a")
        self.reg.define("atom.b")
        self.reg.define("composite", prereqs=["atom.a", "atom.b"])
        # Make atom.a strong, atom.b weak
        for _ in range(9):
            self.reg.record("atom.a", success=True)
        for _ in range(9):
            self.reg.record("atom.b", success=False)
        conf = self.reg.composite_confidence("composite")
        # Min should ≈ atom.b's ~0.1
        self.assertLess(conf, 0.2)

    def test_composite_missing_prereq_returns_zero(self) -> None:
        self.reg.define("c", prereqs=["missing"])
        self.assertEqual(self.reg.composite_confidence("c"), 0.0)


class TestWithSkillContext(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # Swap the singleton registry to a temp one for hermeticity
        self._orig = sk._REGISTRY
        sk._REGISTRY = sk.SkillRegistry(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        sk._REGISTRY = self._orig
        self._tmp.cleanup()

    def test_success_path_records_win(self) -> None:
        with sk.with_skill("x"):
            pass
        s = sk.registry().get("x")
        self.assertEqual(s.wins, 1)

    def test_exception_records_loss_and_reraises(self) -> None:
        with self.assertRaises(RuntimeError):
            with sk.with_skill("x"):
                raise RuntimeError("boom")
        s = sk.registry().get("x")
        self.assertEqual(s.uses, 1)
        self.assertEqual(s.wins, 0)


if __name__ == "__main__":
    unittest.main()
