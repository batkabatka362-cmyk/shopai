"""World model tests — update / predict / fallback / rank."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import world_model as wm


class TestContext(unittest.TestCase):
    def test_tuple_and_coarsen(self) -> None:
        c = wm.Context(
            niche="audio", price_band="premium",
            margin_band="high", copy_tone="luxury",
        )
        self.assertEqual(
            c.as_tuple(),
            ("audio", "premium", "high", "luxury"),
        )
        self.assertEqual(
            c.coarsened(2).as_tuple(),
            ("audio", "premium", "*", "*"),
        )
        self.assertEqual(
            c.coarsened(0).as_tuple(),
            ("*", "*", "*", "*"),
        )


class TestUpdatePredict(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.model = wm.WorldModel(Path(self._tmp.name) / "w.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_single_update_then_predict(self) -> None:
        ctx = wm.Context(niche="audio")
        # Need 2+ samples to pass predict's min-threshold.
        self.model.update(ctx, "launch", "roas", 2.1)
        self.model.update(ctx, "launch", "roas", 2.3)
        pred = self.model.predict(ctx, "launch", "roas")
        self.assertGreater(pred.samples, 0)
        self.assertAlmostEqual(pred.mean, 2.2, places=2)
        self.assertEqual(pred.specificity, 4)

    def test_unknown_action_returns_uninformed(self) -> None:
        pred = self.model.predict(
            wm.Context(), "mystery_action", "roas",
        )
        self.assertEqual(pred.band, "uninformed")
        self.assertEqual(pred.samples, 0)

    def test_fallback_collapses_to_marginal(self) -> None:
        # Populate only the marginal (*, *, *, *). Querying a specific
        # context should still return data via the fallback chain.
        for v in (1.5, 1.8, 2.1):
            self.model.update(wm.Context(niche="unknown"),
                              "launch", "roas", v)
        pred = self.model.predict(
            wm.Context(niche="gardening"),  # never seen
            "launch", "roas",
        )
        self.assertGreater(pred.samples, 0)
        self.assertLess(pred.specificity, 4)

    def test_no_data_is_uninformed(self) -> None:
        pred = self.model.predict(
            wm.Context(niche="new"), "launch", "roas",
        )
        self.assertEqual(pred.band, "uninformed")

    def test_running_variance_updates(self) -> None:
        ctx = wm.Context(niche="apparel")
        for v in (1.0, 3.0, 5.0):
            self.model.update(ctx, "launch", "roas", v)
        pred = self.model.predict(ctx, "launch", "roas")
        self.assertAlmostEqual(pred.mean, 3.0, places=2)
        self.assertGreater(pred.stdev, 0)

    def test_invalid_kpi_silently_ignored(self) -> None:
        ctx = wm.Context()
        # Should not raise.
        self.model.update(ctx, "launch", "nonsense_kpi", 99)
        pred = self.model.predict(ctx, "launch", "nonsense_kpi")
        self.assertEqual(pred.band, "uninformed")


class TestRankActions(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.model = wm.WorldModel(Path(self._tmp.name) / "w.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_rank_puts_best_action_first(self) -> None:
        ctx = wm.Context(niche="audio")
        for v in (3.5, 3.8, 4.0):
            self.model.update(ctx, "scale", "roas", v)
        for v in (1.2, 1.4):
            self.model.update(ctx, "launch", "roas", v)
        ranking = self.model.rank_actions(ctx, "roas")
        top_action = ranking[0][0]
        self.assertEqual(top_action, "scale")


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        db = Path(tmp.name) / "p.db"
        m1 = wm.WorldModel(db)
        m1.update(wm.Context(niche="tech"), "launch", "roas", 2.0)
        m1.update(wm.Context(niche="tech"), "launch", "roas", 2.4)
        m2 = wm.WorldModel(db)
        pred = m2.predict(wm.Context(niche="tech"), "launch", "roas")
        self.assertGreater(pred.samples, 0)
        self.assertAlmostEqual(pred.mean, 2.2, places=2)
        tmp.cleanup()


class TestSummary(unittest.TestCase):
    def test_summary_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = wm.WorldModel(Path(tmp.name) / "s.db")
        m.update(wm.Context(niche="a"), "launch", "roas", 1.0)
        m.update(wm.Context(niche="b"), "scale", "cvr", 0.05)
        summary = m.summary()
        self.assertGreater(summary["cells_with_data"], 0)
        self.assertGreater(summary["total_observations"], 0)
        tmp.cleanup()


class TestBulkIngest(unittest.TestCase):
    def test_ingest_records(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = wm.WorldModel(Path(tmp.name) / "b.db")
        records = [
            {"context": {"niche": "x"}, "action": "launch",
             "kpi": "roas", "value": 2.0},
            {"context": {"niche": "x"}, "action": "launch",
             "kpi": "roas", "value": 2.2},
            {"context": {"niche": "x"}, "action": "bogus",
             "kpi": "roas", "value": 99},
        ]
        count = m.ingest_records(records)
        self.assertEqual(count, 3)
        pred = m.predict(wm.Context(niche="x"), "launch", "roas")
        self.assertAlmostEqual(pred.mean, 2.1, places=2)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
