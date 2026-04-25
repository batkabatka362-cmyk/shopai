"""Trust calibrator tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import trust_calibrator as tc


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = tc.TrustCalibrator(Path(self._tmp.name) / "t.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_register_with_priors(self) -> None:
        s = self.c.register(
            "shopify_api", kind="api",
            prior_alpha=20, prior_beta=1,
        )
        self.assertGreater(s.trust, 0.9)

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.c.register("")

    def test_uniform_prior_by_default(self) -> None:
        s = self.c.register("new_source")
        self.assertAlmostEqual(s.trust, 0.5)


class TestUpdate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = tc.TrustCalibrator(Path(self._tmp.name) / "t.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_correct_raises_trust(self) -> None:
        for _ in range(10):
            self.c.update("src", correct=True)
        s = self.c.get("src")
        self.assertGreater(s.trust, 0.8)

    def test_incorrect_lowers_trust(self) -> None:
        for _ in range(10):
            self.c.update("src", correct=False)
        s = self.c.get("src")
        self.assertLess(s.trust, 0.2)

    def test_auto_register_on_update(self) -> None:
        self.c.update("brand_new", correct=True)
        self.assertIsNotNone(self.c.get("brand_new"))


class TestRank(unittest.TestCase):
    def test_rank_sorts_descending(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = tc.TrustCalibrator(Path(tmp.name) / "t.db")
        for _ in range(20):
            c.update("good", correct=True)
        for _ in range(20):
            c.update("bad", correct=False)
        c.update("neutral", correct=True)
        c.update("neutral", correct=False)
        ranked = c.rank()
        self.assertEqual(ranked[0].name, "good")
        self.assertEqual(ranked[-1].name, "bad")
        tmp.cleanup()


class TestWeight(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = tc.TrustCalibrator(Path(self._tmp.name) / "t.db")
        self.c.register("api", kind="api",
                        prior_alpha=20, prior_beta=1)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_weight_equals_trust_without_context(self) -> None:
        w = self.c.weight("api")
        self.assertGreater(w, 0.9)

    def test_expected_kind_mismatch_halves(self) -> None:
        w = self.c.weight("api", context={"expected_kind": "scrape"})
        # raw trust > 0.9, penalised × 0.5
        self.assertLess(w, 0.6)

    def test_unknown_returns_uniform(self) -> None:
        self.assertEqual(self.c.weight("nobody"), 0.5)

    def test_min_samples_caps_trust(self) -> None:
        # Only 1 observed update — below the min_samples cap.
        self.c.register("fresh")
        self.c.update("fresh", correct=True)
        w = self.c.weight("fresh", context={"min_samples": 5})
        self.assertLessEqual(w, 0.5)


class TestDecay(unittest.TestCase):
    def test_decay_pulls_toward_uniform(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = tc.TrustCalibrator(Path(tmp.name) / "t.db")
        for _ in range(20):
            c.update("old", correct=True)
        # Backdate last_update
        import sqlite3
        conn = sqlite3.connect(str(c._db))
        conn.execute(
            "UPDATE sources SET last_update=? WHERE name=?",
            (time.time() - 365 * 86_400, "old"),
        )
        conn.commit()
        conn.close()
        old_trust = c.trust("old")
        n = c.decay_stale(half_life_days=30.0)
        self.assertEqual(n, 1)
        self.assertLess(c.trust("old"), old_trust)
        tmp.cleanup()

    def test_fresh_source_not_decayed(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = tc.TrustCalibrator(Path(tmp.name) / "t.db")
        for _ in range(5):
            c.update("fresh", correct=True)
        n = c.decay_stale(half_life_days=30.0)
        self.assertEqual(n, 0)
        tmp.cleanup()


class TestConsensus(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = tc.TrustCalibrator(Path(self._tmp.name) / "t.db")
        for _ in range(20):
            self.c.update("trusted", correct=True)
        self.c.update("noisy", correct=False)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_trusted_source_wins_consensus(self) -> None:
        claims = [
            ("trusted", "value_A"),
            ("noisy", "value_B"),
        ]
        winner, weight = self.c.consensus(claims)
        self.assertEqual(winner, "value_A")

    def test_empty_claims_returns_none(self) -> None:
        self.assertIsNone(self.c.consensus([]))

    def test_consensus_handles_dicts(self) -> None:
        claims = [
            ("trusted", {"x": 1, "y": 2}),
            ("noisy", {"x": 1, "y": 3}),
        ]
        winner, _ = self.c.consensus(claims)
        self.assertEqual(winner, {"x": 1, "y": 2})


if __name__ == "__main__":
    unittest.main()
