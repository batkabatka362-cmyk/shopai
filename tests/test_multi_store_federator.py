"""Multi-store federator tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import multi_store_federator as msf


class TestRegister(unittest.TestCase):
    def test_register_returns_spec(self) -> None:
        f = msf.MultiStoreFederator()
        spec = f.register_store("a", traits={"niche": "audio"})
        self.assertEqual(spec.store_id, "a")

    def test_blank_id_raises(self) -> None:
        f = msf.MultiStoreFederator()
        with self.assertRaises(ValueError):
            f.register_store("")

    def test_bad_weight_raises(self) -> None:
        f = msf.MultiStoreFederator()
        with self.assertRaises(ValueError):
            f.register_store("a", weight=0)


class TestObserve(unittest.TestCase):
    def setUp(self) -> None:
        self.f = msf.MultiStoreFederator()
        self.f.register_store("a")

    def test_observe_accumulates(self) -> None:
        self.f.observe("a", "rule1", wins=3, uses=5)
        self.f.observe("a", "rule1", wins=2, uses=3)
        rep = self.f.federated_score("a", "rule1")
        # win rate = (5+1) / (8+2) = 0.6
        self.assertAlmostEqual(rep.federated_score, 0.6, places=2)

    def test_zero_obs_skipped(self) -> None:
        self.f.observe("a", "rule1", wins=0, uses=0)
        rep = self.f.federated_score("a", "rule1")
        # Single obs with uses=0 → not counted → score 0
        self.assertEqual(rep.federated_score, 0.0)

    def test_blank_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.f.observe("", "rule1")
        with self.assertRaises(ValueError):
            self.f.observe("a", "")

    def test_wins_gt_uses_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.f.observe("a", "rule1", wins=5, uses=3)


class TestSimilarity(unittest.TestCase):
    def test_identical_traits_full(self) -> None:
        sim = msf._trait_similarity(
            {"niche": "audio", "currency": "USD"},
            {"niche": "audio", "currency": "USD"},
        )
        self.assertEqual(sim, 1.0)

    def test_disjoint_zero(self) -> None:
        sim = msf._trait_similarity(
            {"a": 1}, {"b": 2},
        )
        self.assertEqual(sim, 0.0)

    def test_partial_overlap(self) -> None:
        sim = msf._trait_similarity(
            {"a": 1, "b": 2},
            {"a": 1, "b": 9},
        )
        # Shared (a, 1), distinct (b, 2) and (b, 9) → 1/3
        self.assertAlmostEqual(sim, 1 / 3)

    def test_empty_either_zero(self) -> None:
        self.assertEqual(msf._trait_similarity({}, {"a": 1}), 0.0)


class TestFederation(unittest.TestCase):
    def test_local_observations_dominate(self) -> None:
        f = msf.MultiStoreFederator()
        f.register_store("local", traits={"niche": "audio"})
        f.register_store("other", traits={"niche": "fashion"})
        f.observe("local", "rule", wins=8, uses=10)
        f.observe("other", "rule", wins=2, uses=10)
        rep = f.federated_score("local", "rule")
        # Local boost + zero similarity to other → score near local
        self.assertGreater(rep.federated_score, 0.6)

    def test_similar_store_contributes(self) -> None:
        f = msf.MultiStoreFederator()
        f.register_store("a", traits={"niche": "audio", "country": "us"})
        f.register_store("b", traits={"niche": "audio", "country": "eu"})
        # only b has data
        f.observe("b", "rule1", wins=8, uses=10)
        rep = f.federated_score("a", "rule1")
        # Some shared traits → b contributes → score > 0
        self.assertGreater(rep.federated_score, 0.0)
        self.assertEqual(rep.contributors[0]["store_id"], "b")

    def test_disjoint_store_filtered_by_floor(self) -> None:
        f = msf.MultiStoreFederator()
        f.register_store("a", traits={"niche": "audio"})
        f.register_store("b", traits={"niche": "fashion"})
        f.observe("b", "rule1", wins=8, uses=10)
        rep = f.federated_score(
            "a", "rule1", similarity_floor=0.5,
        )
        self.assertEqual(rep.federated_score, 0.0)

    def test_unknown_target_raises(self) -> None:
        f = msf.MultiStoreFederator()
        with self.assertRaises(ValueError):
            f.federated_score("nope", "rule1")


class TestBestRules(unittest.TestCase):
    def test_ranks_by_score(self) -> None:
        f = msf.MultiStoreFederator()
        f.register_store("s", traits={"niche": "audio"})
        f.observe("s", "good", wins=10, uses=10)
        f.observe("s", "bad", wins=0, uses=10)
        f.observe("s", "tiny", wins=2, uses=2)   # below default min_uses=5
        ranked = f.best_rules_for("s", min_uses=5)
        names = [r.rule_id for r in ranked]
        self.assertEqual(names, ["good", "bad"])

    def test_unknown_store_raises(self) -> None:
        f = msf.MultiStoreFederator()
        with self.assertRaises(ValueError):
            f.best_rules_for("nope")


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "f.db"
        first = msf.MultiStoreFederator(db_path=path)
        first.register_store("a", traits={"x": "y"})
        first.observe("a", "rule", wins=3, uses=5)
        first.close()
        second = msf.MultiStoreFederator(db_path=path)
        rep = second.federated_score("a", "rule")
        self.assertGreater(rep.federated_score, 0.0)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        f = msf.MultiStoreFederator()
        f.register_store("a")
        f.register_store("b")
        f.observe("a", "rule1", wins=1, uses=2)
        s = f.stats()
        self.assertEqual(s["stores"], 2)
        self.assertEqual(s["observations"], 1)
        self.assertEqual(s["rules"], 1)


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        f = msf.MultiStoreFederator()
        f.register_store("a")
        f.observe("a", "rule", wins=1, uses=2)
        d = f.federated_score("a", "rule").as_dict()
        self.assertIn("contributors", d)
        self.assertIn("federated_score", d)


if __name__ == "__main__":
    unittest.main()
