"""Imitation learner tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import imitation_learner as il


class TestObserve(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = il.ImitationLearner()

    def test_empty_sequence_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.lib.observe(
                situation_fields={"niche": "pet"},
                action_sequence=[],
                outcome_quality=0.9,
            )

    def test_bad_quality_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.lib.observe(
                situation_fields={"niche": "pet"},
                action_sequence=[{"kind": "publish"}],
                outcome_quality=1.5,
            )

    def test_creates_new_template(self) -> None:
        tpl = self.lib.observe(
            situation_fields={"niche": "pet", "aov": "40-60"},
            action_sequence=[
                {"kind": "create", "sku": "p1"},
                {"kind": "publish", "sku": "p1"},
            ],
            outcome_quality=0.8,
            source="self",
        )
        self.assertEqual(tpl.count_observed, 1)
        self.assertEqual(tpl.avg_quality, 0.8)

    def test_observe_increments_existing(self) -> None:
        self.lib.observe(
            situation_fields={"niche": "pet"},
            action_sequence=[{"kind": "publish"}],
            outcome_quality=0.8,
        )
        tpl = self.lib.observe(
            situation_fields={"niche": "pet"},
            action_sequence=[{"kind": "publish"}],
            outcome_quality=0.6,
            source="peer_store",
        )
        self.assertEqual(tpl.count_observed, 2)
        self.assertAlmostEqual(tpl.avg_quality, 0.7)
        self.assertEqual(tpl.source_counts["self"], 1)
        self.assertEqual(tpl.source_counts["peer_store"], 1)

    def test_different_sequence_different_template(self) -> None:
        self.lib.observe(
            situation_fields={"niche": "pet"},
            action_sequence=[{"kind": "publish"}],
            outcome_quality=0.8,
        )
        self.lib.observe(
            situation_fields={"niche": "pet"},
            action_sequence=[
                {"kind": "publish"}, {"kind": "ad_launch"},
            ],
            outcome_quality=0.8,
        )
        self.assertEqual(self.lib.stats()["templates"], 2)

    def test_drops_transient_fields(self) -> None:
        self.lib.observe(
            situation_fields={"niche": "pet"},
            action_sequence=[
                {"kind": "publish", "ts": 100, "id": "a1"},
            ],
            outcome_quality=0.8,
        )
        tpl = self.lib.observe(
            situation_fields={"niche": "pet"},
            action_sequence=[
                {"kind": "publish", "ts": 500, "id": "a2"},
            ],
            outcome_quality=0.8,
        )
        # Same signature → single template
        self.assertEqual(tpl.count_observed, 2)


class TestMatch(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = il.ImitationLearner()
        self.lib.observe(
            situation_fields={
                "niche": "pet", "aov": "40-60",
            },
            action_sequence=[
                {"kind": "create"}, {"kind": "publish"},
            ],
            outcome_quality=0.9,
        )

    def test_match_full(self) -> None:
        m = self.lib.match(
            {"niche": "pet", "aov": "40-60"},
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.similarity, 1.0)

    def test_match_partial(self) -> None:
        m = self.lib.match({"niche": "pet"})
        self.assertIsNotNone(m)
        self.assertLess(m.similarity, 1.0)
        self.assertGreater(m.similarity, 0.0)

    def test_no_match(self) -> None:
        m = self.lib.match({"niche": "tech"})
        self.assertIsNone(m)

    def test_empty_situation(self) -> None:
        self.assertIsNone(self.lib.match({}))

    def test_min_quality_filters(self) -> None:
        self.lib.observe(
            situation_fields={"niche": "toy"},
            action_sequence=[{"kind": "publish"}],
            outcome_quality=0.2,
        )
        m = self.lib.match(
            {"niche": "toy"}, min_quality=0.5,
        )
        self.assertIsNone(m)


class TestTop(unittest.TestCase):
    def test_top_ranks_by_quality(self) -> None:
        lib = il.ImitationLearner()
        lib.observe(
            situation_fields={"k": "low"},
            action_sequence=[{"kind": "a"}],
            outcome_quality=0.2,
        )
        lib.observe(
            situation_fields={"k": "high"},
            action_sequence=[{"kind": "a"}],
            outcome_quality=0.9,
        )
        top = lib.top(limit=2)
        self.assertEqual(top[0].situation_fields["k"], "high")


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "il.db"
        first = il.ImitationLearner(path)
        first.observe(
            situation_fields={"niche": "pet"},
            action_sequence=[{"kind": "publish"}],
            outcome_quality=0.8,
        )
        first.close()
        second = il.ImitationLearner(path)
        s = second.stats()
        self.assertEqual(s["templates"], 1)
        m = second.match({"niche": "pet"})
        self.assertIsNotNone(m)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        lib = il.ImitationLearner()
        lib.observe(
            situation_fields={"niche": "pet"},
            action_sequence=[{"kind": "publish"}],
            outcome_quality=0.8,
            source="peer_store",
        )
        s = lib.stats()
        self.assertEqual(s["templates"], 1)
        self.assertIn("peer_store", s["sources"])


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        lib = il.ImitationLearner()
        lib.observe(
            situation_fields={"k": "v"},
            action_sequence=[{"kind": "a"}],
            outcome_quality=0.5,
        )
        self.assertEqual(lib.reset(), 1)


class TestDict(unittest.TestCase):
    def test_template_serialises(self) -> None:
        lib = il.ImitationLearner()
        tpl = lib.observe(
            situation_fields={"n": "p"},
            action_sequence=[{"kind": "a"}],
            outcome_quality=0.8,
            source="self",
        )
        d = tpl.as_dict()
        self.assertEqual(d["dominant_source"], "self")
        self.assertIn("avg_quality", d)


if __name__ == "__main__":
    unittest.main()
