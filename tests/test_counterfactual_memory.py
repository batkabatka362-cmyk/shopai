"""Counterfactual memory tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory import counterfactual_memory as cm


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = cm.CounterfactualMemory(
            Path(self._tmp.name) / "cf.db",
        )

    def tearDown(self) -> None:
        self.m.close()
        self._tmp.cleanup()

    def test_record_returns_item(self) -> None:
        cf = self.m.record(
            context={"niche": "audio"},
            chosen_action="kill",
            alternative_action="scale",
            simulated_outcome=3.0,
        )
        self.assertEqual(cf.chosen_action, "kill")
        self.assertIsNone(cf.actual_outcome)
        self.assertIsNone(cf.regret)

    def test_blank_chosen_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record(
                context={}, chosen_action="",
                alternative_action="x", simulated_outcome=1.0,
            )

    def test_blank_alternative_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record(
                context={}, chosen_action="x",
                alternative_action="", simulated_outcome=1.0,
            )

    def test_attach_actual_closes_loop(self) -> None:
        cf = self.m.record(
            context={}, chosen_action="a",
            alternative_action="b", simulated_outcome=5.0,
        )
        self.assertTrue(self.m.attach_actual(cf.id, 2.0))
        closed = self.m.get(cf.id)
        self.assertEqual(closed.actual_outcome, 2.0)
        self.assertEqual(closed.regret, 3.0)

    def test_attach_actual_unknown_false(self) -> None:
        self.assertFalse(self.m.attach_actual("nope", 1.0))

    def test_remove(self) -> None:
        cf = self.m.record(
            context={}, chosen_action="a",
            alternative_action="b", simulated_outcome=1.0,
        )
        self.assertTrue(self.m.remove(cf.id))
        self.assertFalse(self.m.remove(cf.id))


class TestFindSimilar(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = cm.CounterfactualMemory(
            Path(self._tmp.name) / "cf.db",
        )

    def tearDown(self) -> None:
        self.m.close()
        self._tmp.cleanup()

    def test_exact_match_top(self) -> None:
        self.m.record(
            context={"niche": "audio", "price": 30},
            chosen_action="kill", alternative_action="scale",
            simulated_outcome=1.0,
        )
        self.m.record(
            context={"niche": "fashion", "price": 100},
            chosen_action="kill", alternative_action="scale",
            simulated_outcome=1.0,
        )
        matches = self.m.find_similar(
            {"niche": "audio", "price": 30},
        )
        self.assertEqual(
            matches[0][0].context["niche"], "audio",
        )

    def test_tag_filter(self) -> None:
        self.m.record(
            context={"x": 1},
            chosen_action="a", alternative_action="b",
            simulated_outcome=1.0, tags=("launch",),
        )
        self.m.record(
            context={"x": 1},
            chosen_action="a", alternative_action="b",
            simulated_outcome=1.0, tags=("refund",),
        )
        matches = self.m.find_similar({"x": 1}, tags=("launch",))
        self.assertEqual(len(matches), 1)

    def test_empty_memory_empty_list(self) -> None:
        self.assertEqual(
            self.m.find_similar({"x": 1}), [],
        )


class TestTopRegrets(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = cm.CounterfactualMemory(
            Path(self._tmp.name) / "cf.db",
        )

    def tearDown(self) -> None:
        self.m.close()
        self._tmp.cleanup()

    def test_largest_regret_first(self) -> None:
        a = self.m.record(
            context={}, chosen_action="a",
            alternative_action="b", simulated_outcome=10.0,
        )
        b = self.m.record(
            context={}, chosen_action="a",
            alternative_action="b", simulated_outcome=3.0,
        )
        self.m.attach_actual(a.id, 1.0)   # regret 9
        self.m.attach_actual(b.id, 1.0)   # regret 2
        top = self.m.top_regrets(k=2)
        self.assertEqual(top[0].id, a.id)

    def test_open_counterfactuals_excluded(self) -> None:
        self.m.record(
            context={}, chosen_action="a",
            alternative_action="b", simulated_outcome=100.0,
        )
        # Never closed → not in top regrets
        self.assertEqual(self.m.top_regrets(), [])


class TestRealisedRegret(unittest.TestCase):
    def test_no_closed_zero(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = cm.CounterfactualMemory(Path(tmp.name) / "cf.db")
        stats = m.realised_regret()
        self.assertEqual(stats["n_closed"], 0)
        m.close()
        tmp.cleanup()

    def test_mean_and_max(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = cm.CounterfactualMemory(Path(tmp.name) / "cf.db")
        a = m.record(
            context={}, chosen_action="a",
            alternative_action="b", simulated_outcome=10,
        )
        b = m.record(
            context={}, chosen_action="a",
            alternative_action="b", simulated_outcome=4,
        )
        m.attach_actual(a.id, 1)   # regret 9
        m.attach_actual(b.id, 3)   # regret 1
        stats = m.realised_regret()
        self.assertEqual(stats["n_closed"], 2)
        self.assertAlmostEqual(stats["mean_regret"], 5.0)
        self.assertAlmostEqual(stats["max_regret"], 9.0)
        m.close()
        tmp.cleanup()


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "cf.db"
        first = cm.CounterfactualMemory(path)
        cf = first.record(
            context={"niche": "audio"},
            chosen_action="kill",
            alternative_action="scale",
            simulated_outcome=5.0,
            tags=("launch",),
        )
        first.attach_actual(cf.id, 2.0)
        first.close()
        second = cm.CounterfactualMemory(path)
        loaded = second.get(cf.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.regret, 3.0)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = cm.CounterfactualMemory(Path(tmp.name) / "cf.db")
        cf = m.record(
            context={}, chosen_action="a",
            alternative_action="b", simulated_outcome=1.0,
        )
        m.attach_actual(cf.id, 0.0)
        m.record(
            context={}, chosen_action="a",
            alternative_action="b", simulated_outcome=2.0,
        )
        s = m.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["closed"], 1)
        self.assertEqual(s["open"], 1)
        m.close()
        tmp.cleanup()


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = cm.CounterfactualMemory(Path(tmp.name) / "cf.db")
        cf = m.record(
            context={"niche": "audio"},
            chosen_action="a", alternative_action="b",
            simulated_outcome=5.0, tags=("t",),
        )
        d = cf.as_dict()
        self.assertEqual(d["chosen_action"], "a")
        self.assertEqual(d["tags"], ["t"])
        m.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
