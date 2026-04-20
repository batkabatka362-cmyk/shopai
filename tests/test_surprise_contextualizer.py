"""Surprise contextualizer tests."""
from __future__ import annotations

import unittest

from core.brain import surprise_contextualizer as sc


class TestConfig(unittest.TestCase):
    def test_bad_history_raises(self) -> None:
        with self.assertRaises(ValueError):
            sc.SurpriseContextualizer(history_size=5)

    def test_bad_match_limit_raises(self) -> None:
        with self.assertRaises(ValueError):
            sc.SurpriseContextualizer(match_limit=0)


class TestContextualise(unittest.TestCase):
    def setUp(self) -> None:
        self.c = sc.SurpriseContextualizer()

    def test_blank_kpi_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.c.contextualise(
                kpi="", expected=1.0, observed=2.0,
            )

    def test_happy_path(self) -> None:
        b = self.c.contextualise(
            kpi="roas",
            expected=1.5,
            observed=0.8,
            situation={"niche": "pet"},
        )
        self.assertEqual(b.kpi, "roas")
        self.assertAlmostEqual(b.delta, -0.7)

    def test_no_similar_past(self) -> None:
        b = self.c.contextualise(
            kpi="roas",
            expected=1.5, observed=0.8,
        )
        self.assertEqual(b.similar_past, [])

    def test_finds_similar_past(self) -> None:
        self.c.contextualise(
            kpi="roas",
            expected=1.5, observed=0.8,
            situation={"niche": "pet", "aov": "40-60"},
        )
        self.c.contextualise(
            kpi="roas",
            expected=1.5, observed=0.9,
            situation={"niche": "pet", "aov": "40-60"},
        )
        b = self.c.contextualise(
            kpi="roas",
            expected=1.5, observed=0.7,
            situation={"niche": "pet", "aov": "40-60"},
        )
        self.assertGreater(len(b.similar_past), 0)

    def test_different_kpi_not_matched(self) -> None:
        self.c.contextualise(
            kpi="cpm",
            expected=10, observed=25,
            situation={"niche": "pet"},
        )
        b = self.c.contextualise(
            kpi="roas",
            expected=1.5, observed=0.5,
            situation={"niche": "pet"},
        )
        self.assertEqual(b.similar_past, [])


class TestCauseHints(unittest.TestCase):
    def test_register_and_surface(self) -> None:
        c = sc.SurpriseContextualizer()
        c.register_cause_hint("roas", "CPM rose 2x")
        b = c.contextualise(
            kpi="roas",
            expected=1.5, observed=0.5,
        )
        self.assertIn("CPM rose 2x", b.candidate_causes)

    def test_blank_hint_raises(self) -> None:
        c = sc.SurpriseContextualizer()
        with self.assertRaises(ValueError):
            c.register_cause_hint("", "x")
        with self.assertRaises(ValueError):
            c.register_cause_hint("x", "")


class TestQueries(unittest.TestCase):
    def setUp(self) -> None:
        self.c = sc.SurpriseContextualizer()
        self.c.contextualise(
            kpi="roas", expected=1.5, observed=0.5,
            ts=100.0,
        )
        self.c.contextualise(
            kpi="cpm", expected=10, observed=25,
            ts=200.0,
        )

    def test_recent_newest_first(self) -> None:
        r = self.c.recent()
        self.assertEqual(r[0].kpi, "cpm")

    def test_by_kpi(self) -> None:
        roas = self.c.by_kpi("roas")
        self.assertEqual(len(roas), 1)

    def test_stats(self) -> None:
        s = self.c.stats()
        self.assertEqual(s["buffered"], 2)
        self.assertEqual(set(s["kpis"]), {"roas", "cpm"})


class TestHistoryBounded(unittest.TestCase):
    def test_bounded(self) -> None:
        c = sc.SurpriseContextualizer(history_size=10)
        for i in range(20):
            c.contextualise(
                kpi="x",
                expected=0.0,
                observed=1.0,
                ts=float(i),
            )
        self.assertEqual(c.stats()["buffered"], 10)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        c = sc.SurpriseContextualizer()
        c.contextualise(
            kpi="x", expected=0, observed=1,
        )
        self.assertEqual(c.reset(), 1)


class TestDict(unittest.TestCase):
    def test_event_serialises(self) -> None:
        e = sc.SurpriseEvent(
            id="i", kpi="k",
            expected=1, observed=2,
            situation={}, ts=0.0,
        )
        d = e.as_dict()
        self.assertEqual(d["delta"], 1.0)

    def test_bundle_serialises(self) -> None:
        c = sc.SurpriseContextualizer()
        b = c.contextualise(
            kpi="x", expected=1, observed=2,
        )
        d = b.as_dict()
        self.assertIn("first_action", d)


if __name__ == "__main__":
    unittest.main()
