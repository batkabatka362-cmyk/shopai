"""Adaptive prompt bank — Thompson sampling + mutation tests."""
from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from core.brain import adaptive_prompts as ap


class TestMutations(unittest.TestCase):
    def test_swap_sentences(self) -> None:
        s = "First. Second. Third."
        out = ap.swap_sentences(s)
        self.assertIn("Third. Second. First", out)

    def test_add_constraint(self) -> None:
        self.assertEqual(
            ap.add_constraint("hello world", "stop."),
            "hello world stop.",
        )

    def test_add_constraint_idempotent(self) -> None:
        self.assertEqual(
            ap.add_constraint("hello stop.", "stop."),
            "hello stop.",
        )

    def test_tighten_removes_filler(self) -> None:
        self.assertEqual(
            ap.tighten("This is really actually just a test"),
            "This is a test",
        )


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.bank = ap.PromptBank(Path(self._tmp.name) / "p.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_register_seeds_variants(self) -> None:
        vs = self.bank.register("x", ["a", "b"])
        self.assertEqual(len(vs), 2)
        self.assertEqual({v.text for v in vs}, {"a", "b"})

    def test_register_idempotent(self) -> None:
        self.bank.register("x", ["a"])
        second = self.bank.register("x", ["a"])
        self.assertEqual(len(second), 1)
        self.assertEqual(len(self.bank.list_all("x")), 1)


class TestPick(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.bank = ap.PromptBank(Path(self._tmp.name) / "p.db")
        self.bank.register("x", ["variant A", "variant B"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pick_returns_a_variant(self) -> None:
        v = self.bank.pick("x", rng_seed=1)
        self.assertIsNotNone(v)
        self.assertIn(v.text, {"variant A", "variant B"})
        # Use count incremented
        same = next(x for x in self.bank.list_all("x") if x.id == v.id)
        self.assertEqual(same.uses, 1)

    def test_pick_unknown_prompt_returns_none(self) -> None:
        self.assertIsNone(self.bank.pick("nope"))


class TestScore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.bank = ap.PromptBank(Path(self._tmp.name) / "p.db")
        self.bank.register("x", ["one", "two"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_positive_reward_pushes_alpha_up(self) -> None:
        vs = self.bank.list_all("x")
        self.bank.score(vs[0].id, reward=1.0)
        updated = [v for v in self.bank.list_all("x") if v.id == vs[0].id][0]
        self.assertGreater(updated.alpha, 1.0)
        self.assertAlmostEqual(updated.beta, 1.0)

    def test_zero_reward_pushes_beta_up(self) -> None:
        vs = self.bank.list_all("x")
        self.bank.score(vs[0].id, reward=0.0)
        updated = [v for v in self.bank.list_all("x") if v.id == vs[0].id][0]
        self.assertAlmostEqual(updated.alpha, 1.0)
        self.assertGreater(updated.beta, 1.0)

    def test_reward_clamped(self) -> None:
        vs = self.bank.list_all("x")
        self.bank.score(vs[0].id, reward=5.0)
        updated = [v for v in self.bank.list_all("x") if v.id == vs[0].id][0]
        # reward was clamped to 1.0
        self.assertAlmostEqual(updated.alpha, 2.0)


class TestPruneAndMutate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.bank = ap.PromptBank(Path(self._tmp.name) / "p.db")
        self.bank.register("x", ["winner text.", "loser text."])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_prune_fires_when_intervals_disjoint(self) -> None:
        vs = self.bank.list_all("x")
        winner = next(v for v in vs if v.text == "winner text.")
        loser = next(v for v in vs if v.text == "loser text.")
        # 30 wins / 30 uses — confident winner
        for _ in range(30):
            self.bank.score(winner.id, reward=1.0)
        # 30 losses / 30 uses — confident loser
        for _ in range(30):
            self.bank.score(loser.id, reward=0.0)
        # The loser should be pruned
        live = self.bank.list_all("x")
        ids = {v.id for v in live}
        self.assertNotIn(loser.id, ids)

    def test_no_prune_with_few_uses(self) -> None:
        vs = self.bank.list_all("x")
        self.bank.score(vs[0].id, reward=1.0)
        self.bank.score(vs[1].id, reward=0.0)
        live = self.bank.list_all("x")
        self.assertEqual(len(live), 2)   # too few samples to prune


if __name__ == "__main__":
    unittest.main()
