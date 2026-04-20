"""Niche discoverer tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents.research.niche_discoverer import (
    NicheDiscoverer, NicheReport, _label_for,
    _DEFAULT_NICHES,
)
from agents.research.winner_searcher import ProductCandidate


def _candidate(**kw):
    defaults = dict(
        source="test",
        external_id="e1",
        title="Pet Slow Feeder",
        price=30,
        cost=10,
        daily_sales=20,
        saturation_score=0.3,
    )
    defaults.update(kw)
    return ProductCandidate(**defaults)


class TestLabelFor(unittest.TestCase):
    def test_pet_from_title(self):
        label = _label_for(
            "Dog Leash Deluxe", (), _DEFAULT_NICHES,
        )
        self.assertEqual(label, "pet")

    def test_kitchen_from_title(self):
        label = _label_for(
            "Electric Blender Pro", (), _DEFAULT_NICHES,
        )
        self.assertEqual(label, "kitchen")

    def test_other_when_no_match(self):
        label = _label_for(
            "Xyzzy Plumbus 9000", (), _DEFAULT_NICHES,
        )
        self.assertEqual(label, "other")

    def test_tags_contribute(self):
        label = _label_for(
            "Mystery Thing",
            ("fitness",),
            _DEFAULT_NICHES,
        )
        self.assertEqual(label, "fitness")

    def test_more_hits_wins(self):
        # "pet" appears once in title, "kitchen" + "bowl" both
        # appear → kitchen wins
        label = _label_for(
            "Pet Kitchen Bowl",
            (),
            _DEFAULT_NICHES,
        )
        self.assertEqual(label, "kitchen")


class TestConfig(unittest.TestCase):
    def test_bad_rising_raises(self):
        with self.assertRaises(ValueError):
            NicheDiscoverer(rising_threshold=1.0)

    def test_bad_falling_raises(self):
        with self.assertRaises(ValueError):
            NicheDiscoverer(falling_threshold=1.2)


class TestDiscoverShape(unittest.TestCase):
    def test_empty_candidates(self):
        d = NicheDiscoverer()
        self.assertEqual(d.discover([]), [])

    def test_single_candidate_one_report(self):
        d = NicheDiscoverer()
        reports = d.discover(
            [_candidate(title="Dog Leash")],
            persist=False,
        )
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].label, "pet")
        self.assertEqual(reports[0].candidate_count, 1)

    def test_multiple_niches_multiple_reports(self):
        d = NicheDiscoverer()
        reports = d.discover(
            [
                _candidate(title="Dog Toy"),
                _candidate(
                    title="Kitchen Knife Set",
                    price=50, cost=15,
                ),
                _candidate(title="Yoga Mat", price=40),
            ],
            persist=False,
        )
        labels = {r.label for r in reports}
        self.assertEqual(
            labels,
            {"pet", "kitchen", "fitness"},
        )

    def test_other_bucket(self):
        d = NicheDiscoverer()
        reports = d.discover(
            [_candidate(title="Xyzzy Plumbus")],
            persist=False,
        )
        self.assertEqual(reports[0].label, "other")

    def test_rollup_sort_desc(self):
        d = NicheDiscoverer()
        reports = d.discover(
            [
                _candidate(
                    title="Dog Toy",
                    daily_sales=1,
                    saturation_score=0.9,
                ),
                _candidate(
                    title="Kitchen Blender",
                    price=50, cost=10,
                    daily_sales=100,
                    saturation_score=0.1,
                ),
            ],
            persist=False,
        )
        # Kitchen has better demand × margin × low saturation
        self.assertEqual(reports[0].label, "kitchen")

    def test_example_titles_honored(self):
        d = NicheDiscoverer()
        reports = d.discover(
            [
                _candidate(title=f"Dog Toy {i}")
                for i in range(10)
            ],
            persist=False,
            example_limit=2,
        )
        self.assertEqual(
            len(reports[0].example_titles), 2,
        )


class TestTrendDirection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "niche.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_all_stable(self):
        d = NicheDiscoverer(self.path)
        reports = d.discover(
            [_candidate(title="Dog Toy")],
        )
        self.assertEqual(
            reports[0].trend_direction, "stable",
        )
        d.close()

    def test_rising_detected(self):
        d = NicheDiscoverer(
            self.path, rising_threshold=1.1,
        )
        # First run: low rollup
        d.discover(
            [_candidate(
                title="Dog Toy",
                daily_sales=1,
                saturation_score=0.8,
            )],
        )
        # Second run: much higher rollup (price bumped, demand up)
        reports = d.discover(
            [_candidate(
                title="Dog Toy",
                price=100, cost=10,
                daily_sales=50,
                saturation_score=0.1,
            )],
        )
        d.close()
        pet = next(r for r in reports if r.label == "pet")
        self.assertEqual(pet.trend_direction, "rising")

    def test_falling_detected(self):
        d = NicheDiscoverer(
            self.path, falling_threshold=0.9,
        )
        d.discover(
            [_candidate(
                title="Dog Toy",
                price=100, cost=10,
                daily_sales=100,
                saturation_score=0.1,
            )],
        )
        reports = d.discover(
            [_candidate(
                title="Dog Toy",
                daily_sales=1,
                saturation_score=0.9,
            )],
        )
        d.close()
        pet = next(r for r in reports if r.label == "pet")
        self.assertEqual(pet.trend_direction, "falling")

    def test_stable_within_band(self):
        d = NicheDiscoverer(
            self.path,
            rising_threshold=1.5,
            falling_threshold=0.5,
        )
        d.discover(
            [_candidate(
                title="Dog Toy",
                price=30, cost=10,
                daily_sales=20,
                saturation_score=0.3,
            )],
        )
        # Same rollup → stable
        reports = d.discover(
            [_candidate(
                title="Dog Toy",
                price=30, cost=10,
                daily_sales=20,
                saturation_score=0.3,
            )],
        )
        d.close()
        pet = next(r for r in reports if r.label == "pet")
        self.assertEqual(pet.trend_direction, "stable")


class TestRegistry(unittest.TestCase):
    def test_register_new_niche(self):
        d = NicheDiscoverer()
        d.register_niche("drone", ("drone", "quadcopter"))
        reports = d.discover(
            [_candidate(title="Professional Drone")],
            persist=False,
        )
        self.assertEqual(reports[0].label, "drone")

    def test_blank_label_raises(self):
        d = NicheDiscoverer()
        with self.assertRaises(ValueError):
            d.register_niche("", ("x",))

    def test_empty_tokens_raises(self):
        d = NicheDiscoverer()
        with self.assertRaises(ValueError):
            d.register_niche("x", ())

    def test_unregister(self):
        d = NicheDiscoverer()
        self.assertTrue(d.unregister_niche("pet"))
        # Dog Toy now falls through to "other"
        reports = d.discover(
            [_candidate(title="Dog Toy")],
            persist=False,
        )
        self.assertEqual(reports[0].label, "other")


class TestQueries(unittest.TestCase):
    def test_rising_niches_filter(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "n.db"
            d = NicheDiscoverer(
                path, rising_threshold=1.1,
            )
            d.discover(
                [_candidate(
                    title="Dog Toy",
                    daily_sales=1,
                )],
            )
            d.discover(
                [_candidate(
                    title="Dog Toy",
                    price=100, cost=10,
                    daily_sales=50,
                    saturation_score=0.1,
                )],
            )
            rising = d.rising_niches()
            self.assertEqual(len(rising), 1)
            self.assertEqual(rising[0].label, "pet")
            d.close()
        finally:
            tmp.cleanup()

    def test_history_newest_first(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "n.db"
            d = NicheDiscoverer(path)
            d.discover([_candidate(title="Dog Toy")])
            d.discover([_candidate(title="Dog Toy")])
            hist = d.history("pet", limit=10)
            self.assertEqual(len(hist), 2)
            self.assertGreaterEqual(
                hist[0]["snapshot_ts"],
                hist[1]["snapshot_ts"],
            )
            d.close()
        finally:
            tmp.cleanup()

    def test_stats_shape(self):
        d = NicheDiscoverer()
        s = d.stats()
        self.assertIn("niche_labels", s)
        self.assertIn("pet", s["niche_labels"])


class TestPersistence(unittest.TestCase):
    def test_snapshots_survive_reopen(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "n.db"
            first = NicheDiscoverer(path)
            first.discover(
                [_candidate(title="Dog Toy")],
            )
            first.close()
            second = NicheDiscoverer(path)
            hist = second.history("pet")
            self.assertEqual(len(hist), 1)
            second.close()
        finally:
            tmp.cleanup()


class TestReset(unittest.TestCase):
    def test_reset_clears(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "n.db"
            d = NicheDiscoverer(path)
            d.discover([_candidate(title="Dog Toy")])
            n = d.reset()
            self.assertGreaterEqual(n, 1)
            self.assertEqual(d.history("pet"), [])
            d.close()
        finally:
            tmp.cleanup()


class TestDict(unittest.TestCase):
    def test_report_serialises(self):
        r = NicheReport(
            label="pet", candidate_count=3,
            avg_margin=0.5, avg_demand=20,
            saturation_score=0.3, rollup_score=1.5,
        )
        d = r.as_dict()
        self.assertEqual(d["label"], "pet")
        self.assertEqual(d["candidate_count"], 3)


class TestTrendScorer(unittest.TestCase):
    """Optional external trend signal hook."""

    def test_default_no_scorer_signal_is_zero(self):
        d = NicheDiscoverer()
        r = d.discover(
            [_candidate(title="Dog Toy")], persist=False,
        )
        self.assertEqual(r[0].trend_signal_score, 0.0)
        self.assertAlmostEqual(
            r[0].ranked_score, r[0].rollup_score,
        )

    def test_scorer_boosts_ranked_score(self):
        def scorer(label, tokens):
            return 0.5 if label == "pet" else 0.0

        d = NicheDiscoverer(trend_scorer=scorer)
        r = d.discover(
            [_candidate(title="Dog Toy")], persist=False,
        )
        self.assertAlmostEqual(r[0].trend_signal_score, 0.5)
        self.assertAlmostEqual(
            r[0].ranked_score, r[0].rollup_score * 1.5,
        )

    def test_scorer_reorders_ranking(self):
        # pet has higher rollup naturally, but we boost kitchen more
        def scorer(label, tokens):
            return 0.9 if label == "kitchen" else 0.0

        d = NicheDiscoverer(trend_scorer=scorer)
        reports = d.discover([
            _candidate(
                title="Dog Toy",
                daily_sales=50,
            ),
            _candidate(
                title="Kitchen Blender",
                daily_sales=10,
            ),
        ], persist=False)
        labels = [r.label for r in reports]
        self.assertIn("kitchen", labels)
        self.assertIn("pet", labels)
        kitchen = next(r for r in reports if r.label == "kitchen")
        self.assertGreater(kitchen.trend_signal_score, 0.0)

    def test_scorer_clamped_to_unit(self):
        d = NicheDiscoverer(
            trend_scorer=lambda l, t: 5.0,
        )
        r = d.discover(
            [_candidate(title="Dog Toy")], persist=False,
        )
        self.assertEqual(r[0].trend_signal_score, 1.0)

    def test_scorer_clamped_non_negative(self):
        d = NicheDiscoverer(
            trend_scorer=lambda l, t: -2.0,
        )
        r = d.discover(
            [_candidate(title="Dog Toy")], persist=False,
        )
        self.assertEqual(r[0].trend_signal_score, 0.0)

    def test_scorer_error_degrades_to_zero(self):
        def boom(label, tokens):
            raise RuntimeError("nope")

        d = NicheDiscoverer(trend_scorer=boom)
        r = d.discover(
            [_candidate(title="Dog Toy")], persist=False,
        )
        self.assertEqual(r[0].trend_signal_score, 0.0)


if __name__ == "__main__":
    unittest.main()
