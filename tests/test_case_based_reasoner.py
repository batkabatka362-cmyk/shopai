"""Case-based reasoner tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory import case_based_reasoner as cbr


class TestAdd(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.r = cbr.CaseBasedReasoner(Path(self._tmp.name) / "cb.db")

    def tearDown(self) -> None:
        self.r.close()
        self._tmp.cleanup()

    def test_add_returns_id(self) -> None:
        cid = self.r.add(
            {"niche": "audio"}, action="scale", outcome_score=4.5,
        )
        self.assertTrue(cid)

    def test_blank_action_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.add({"niche": "audio"}, action="", outcome_score=0.0)


class TestRecall(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.r = cbr.CaseBasedReasoner(Path(self._tmp.name) / "cb.db")

    def tearDown(self) -> None:
        self.r.close()
        self._tmp.cleanup()

    def test_empty_base_returns_empty(self) -> None:
        self.assertEqual(self.r.recall({"niche": "audio"}), [])

    def test_exact_match_scores_highest(self) -> None:
        self.r.add(
            {"niche": "audio", "price": 30.0}, "scale", 4.0,
        )
        self.r.add(
            {"niche": "fashion", "price": 80.0}, "kill", 1.0,
        )
        matches = self.r.recall({"niche": "audio", "price": 30.0})
        self.assertEqual(matches[0].case.action, "scale")
        self.assertGreater(matches[0].similarity, 0.8)

    def test_numeric_distance_penalises(self) -> None:
        # Same niche, but price very different
        self.r.add({"niche": "audio", "price": 30.0}, "scale", 4.0)
        self.r.add({"niche": "audio", "price": 31.0}, "scale", 4.0)
        self.r.add({"niche": "audio", "price": 30.0}, "scale", 4.0)
        matches = self.r.recall({"niche": "audio", "price": 30.0}, k=3)
        # Nearest-price case should be ranked first/equal
        top = matches[0]
        self.assertEqual(top.case.situation.get("price"), 30.0)

    def test_action_filter(self) -> None:
        self.r.add({"niche": "audio"}, "scale", 4.0)
        self.r.add({"niche": "audio"}, "kill", 1.0)
        matches = self.r.recall(
            {"niche": "audio"}, k=5, action_filter="kill",
        )
        for m in matches:
            self.assertEqual(m.case.action, "kill")

    def test_min_similarity_filter(self) -> None:
        self.r.add({"niche": "audio"}, "scale", 4.0)
        self.r.add({"niche": "fashion"}, "scale", 4.0)
        matches = self.r.recall(
            {"niche": "audio"}, k=5, min_similarity=0.9,
        )
        # fashion case shouldn't pass (sim=0 vs audio)
        self.assertTrue(all(
            m.case.situation.get("niche") == "audio" for m in matches
        ))


class TestSuggest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.r = cbr.CaseBasedReasoner(Path(self._tmp.name) / "cb.db")

    def tearDown(self) -> None:
        self.r.close()
        self._tmp.cleanup()

    def test_majority_winner(self) -> None:
        for _ in range(5):
            self.r.add({"niche": "audio"}, "scale", 4.0)
        self.r.add({"niche": "audio"}, "kill", 1.0)
        sug = self.r.suggest({"niche": "audio"})
        self.assertEqual(sug["action"], "scale")
        self.assertGreater(sug["confidence"], 0.7)

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(self.r.suggest({"niche": "audio"}))

    def test_mean_similarity_reported(self) -> None:
        self.r.add({"niche": "audio"}, "scale", 4.0)
        sug = self.r.suggest({"niche": "audio"})
        self.assertIn("mean_similarity", sug)


class TestScales(unittest.TestCase):
    def test_single_point_scale_is_finite(self) -> None:
        self.assertEqual(cbr._scale_for([]), 1.0)
        self.assertEqual(cbr._scale_for([5.0]), 5.0)
        self.assertEqual(cbr._scale_for([5.0, 5.0]), 5.0)

    def test_iqr_dominates_with_many_points(self) -> None:
        values = [1, 2, 3, 4, 5, 6, 7, 8]
        s = cbr._scale_for([float(v) for v in values])
        # IQR preferred over full range (7) — expect smaller scale
        self.assertLessEqual(s, 7.0)


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        r = cbr.CaseBasedReasoner(Path(tmp.name) / "cb.db")
        r.add({"x": 1}, "scale", 4.0)
        r.add({"x": 1}, "kill", 1.0)
        s = r.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_action"]["scale"], 1)
        r.close()
        tmp.cleanup()


class TestPrune(unittest.TestCase):
    def test_prune_keeps_newest(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        r = cbr.CaseBasedReasoner(Path(tmp.name) / "cb.db")
        for i in range(20):
            r.add({"i": i}, "scale", float(i))
        n = r.prune(keep_newest=5)
        self.assertEqual(n, 15)
        self.assertEqual(r.stats()["total"], 5)
        r.close()
        tmp.cleanup()

    def test_prune_noop_below_limit(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        r = cbr.CaseBasedReasoner(Path(tmp.name) / "cb.db")
        r.add({"x": 1}, "scale", 4.0)
        self.assertEqual(r.prune(keep_newest=10), 0)
        r.close()
        tmp.cleanup()


class TestDict(unittest.TestCase):
    def test_case_serialises(self) -> None:
        c = cbr.Case(
            id="c1", situation={"x": 1}, action="scale",
            outcome_score=4.0, tags=("a",), ts=1.0,
        )
        d = c.as_dict()
        self.assertEqual(d["action"], "scale")
        self.assertEqual(d["tags"], ["a"])

    def test_match_serialises(self) -> None:
        c = cbr.Case(
            id="c1", situation={"x": 1}, action="scale",
            outcome_score=4.0, tags=(), ts=1.0,
        )
        m = cbr.Match(case=c, similarity=0.8, weighted_score=3.2)
        d = m.as_dict()
        self.assertIn("case", d)
        self.assertIn("similarity", d)


if __name__ == "__main__":
    unittest.main()
