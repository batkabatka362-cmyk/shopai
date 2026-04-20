"""Winner searcher tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agents.research import winner_searcher as ws


def _c(**kw):
    defaults = dict(
        source="test",
        external_id="ext1",
        title="Default Product",
        price=30.0,
        cost=10.0,
        daily_sales=10.0,
        saturation_score=0.3,
    )
    defaults.update(kw)
    return ws.ProductCandidate(**defaults)


class TestCandidate(unittest.TestCase):
    def test_margin_pct(self) -> None:
        c = _c(price=40.0, cost=10.0)
        self.assertAlmostEqual(c.margin_pct, 0.75, places=4)

    def test_margin_zero_price(self) -> None:
        c = _c(price=0.0, cost=5.0)
        self.assertEqual(c.margin_pct, 0.0)

    def test_canonical_key_stable(self) -> None:
        c1 = _c(title="Pet Toy X", source="ali")
        c2 = _c(title="Pet Toy X", source="amazon")
        self.assertEqual(c1.canonical_key(), c2.canonical_key())

    def test_canonical_key_varies(self) -> None:
        c1 = _c(title="Pet Toy X")
        c2 = _c(title="Dog Toy Y")
        self.assertNotEqual(
            c1.canonical_key(), c2.canonical_key(),
        )

    def test_serialises(self) -> None:
        c = _c()
        d = c.as_dict()
        self.assertIn("margin_pct", d)


class TestSource(unittest.TestCase):
    def test_static_source_returns(self) -> None:
        src = ws.StaticWinnerSource([_c(), _c(title="Other")])
        items = src.fetch(limit=10)
        self.assertEqual(len(items), 2)

    def test_static_limit(self) -> None:
        src = ws.StaticWinnerSource([_c() for _ in range(5)])
        self.assertEqual(len(src.fetch(limit=2)), 2)


class TestConfig(unittest.TestCase):
    def test_bad_weights_raise(self) -> None:
        with self.assertRaises(ValueError):
            ws.WinnerSearcher(
                margin_weight=0.5,
                demand_weight=0.5,
                saturation_weight=0.5,
            )

    def test_bad_margin_floor_raises(self) -> None:
        with self.assertRaises(ValueError):
            ws.WinnerSearcher(min_margin_pct=1.5)


class TestSearch(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        # Inject a scratch KB so we don't pollute the default one
        from core.memory.knowledge_base import KnowledgeBase
        self.kb = KnowledgeBase(
            db_path=Path(self.tmp.name) / "k.db",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _searcher(self, candidates):
        return ws.WinnerSearcher(
            sources=[ws.StaticWinnerSource(candidates)],
            knowledge_base=self.kb,
        )

    def test_bad_top_n_raises(self) -> None:
        s = self._searcher([_c()])
        with self.assertRaises(ValueError):
            s.search(top_n=0)

    def test_low_margin_filtered(self) -> None:
        s = ws.WinnerSearcher(
            sources=[ws.StaticWinnerSource([
                _c(title="A", price=10.0, cost=9.5),   # 5% margin
                _c(title="B", price=30.0, cost=10.0),  # 67% margin
            ])],
            knowledge_base=self.kb,
            min_margin_pct=0.15,
        )
        result = s.search(top_n=5, publish=False)
        titles = [r.candidate.title for r in result.ranked]
        self.assertEqual(titles, ["B"])

    def test_dedup_by_title(self) -> None:
        s = self._searcher([
            _c(title="Pet Toy", source="ali",
               daily_sales=10),
            _c(title="Pet Toy", source="amazon",
               daily_sales=50),   # higher demand wins
        ])
        result = s.search(top_n=5, publish=False)
        self.assertEqual(result.deduped, 1)
        # The amazon one (higher demand) wins dedupe
        self.assertEqual(
            result.ranked[0].candidate.source, "amazon",
        )

    def test_ranks_high_score_first(self) -> None:
        s = self._searcher([
            _c(title="Low", daily_sales=1, saturation_score=0.9),
            _c(title="High", daily_sales=50, saturation_score=0.1,
               price=50, cost=10),
        ])
        result = s.search(top_n=2, publish=False)
        self.assertEqual(
            result.ranked[0].candidate.title, "High",
        )

    def test_publishes_to_kb(self) -> None:
        s = self._searcher([_c(title="Winner A")])
        result = s.search(top_n=1, publish=True)
        self.assertEqual(len(result.published), 1)
        # Verify KB has the fact
        subject = result.published[0]
        fact = self.kb.recall(subject, "title")
        self.assertIsNotNone(fact)
        self.assertEqual(fact.object, "Winner A")

    def test_skip_publish_when_disabled(self) -> None:
        s = self._searcher([_c(title="X")])
        result = s.search(top_n=1, publish=False)
        self.assertEqual(result.published, [])


class TestSourceFailures(unittest.TestCase):
    def test_source_exception_isolated(self) -> None:
        class BoomSource(ws.WinnerSource):
            name = "boom"
            def fetch(self, *, limit=100):
                raise RuntimeError("down")
        good = ws.StaticWinnerSource([_c()])
        s = ws.WinnerSearcher(sources=[BoomSource(), good])
        # Shouldn't crash; good source still contributes
        result = s.search(top_n=1, publish=False)
        self.assertEqual(result.candidates_examined, 1)
        self.assertIn("static", result.sources_used)


class TestRegistry(unittest.TestCase):
    def test_register_unregister(self) -> None:
        s = ws.WinnerSearcher()
        src = ws.StaticWinnerSource([_c()], name="abc")
        s.register_source(src)
        self.assertEqual(s.stats()["sources"], 1)
        self.assertTrue(s.unregister_source("abc"))
        self.assertEqual(s.stats()["sources"], 0)


class TestBrainHook(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = os.environ.get("SHOPAI_BRAIN_HOOKS")
        os.environ["SHOPAI_BRAIN_HOOKS"] = "1"
        # Reset brain singletons
        from core.brain import brain_facade
        brain_facade._CONCEPT_FORMER = None
        brain_facade._DECISION_REVERSAL_DETECTOR = None
        self.tmp = tempfile.TemporaryDirectory()
        from core.memory.knowledge_base import KnowledgeBase
        self.kb = KnowledgeBase(
            db_path=Path(self.tmp.name) / "k.db",
        )

    def tearDown(self) -> None:
        if self._orig is None:
            os.environ.pop("SHOPAI_BRAIN_HOOKS", None)
        else:
            os.environ["SHOPAI_BRAIN_HOOKS"] = self._orig
        self.tmp.cleanup()

    def test_winner_ingest_feeds_brain(self) -> None:
        s = ws.WinnerSearcher(
            sources=[ws.StaticWinnerSource([_c(title="W1")])],
            knowledge_base=self.kb,
        )
        s.search(top_n=1, publish=True)
        from core.brain.brain_facade import brain
        snap = brain().introspect()
        # Concept former should have seen at least one observation
        self.assertGreater(snap.concepts.get(
            "total_observations", 0,
        ), 0)
        # Decision reversal detector should have seen one target
        self.assertGreaterEqual(
            snap.reversals.get("tracked_targets", 0), 1,
        )


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        s = ws.WinnerSearcher(
            sources=[ws.StaticWinnerSource([_c()])],
        )
        st = s.stats()
        self.assertEqual(st["sources"], 1)
        self.assertIn("weights", st)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        s = ws.WinnerSearcher(
            sources=[ws.StaticWinnerSource([_c()])],
        )
        s.search(top_n=1, publish=False)
        self.assertEqual(s.reset(), 1)


class TestDict(unittest.TestCase):
    def test_score_serialises(self) -> None:
        s = ws.WinnerSearcher(
            sources=[ws.StaticWinnerSource([_c()])],
        )
        scored = s.score(_c())
        d = scored.as_dict()
        self.assertIn("components", d)

    def test_result_serialises(self) -> None:
        s = ws.WinnerSearcher(
            sources=[ws.StaticWinnerSource([_c()])],
        )
        d = s.search(top_n=1, publish=False).as_dict()
        self.assertIn("ranked", d)


if __name__ == "__main__":
    unittest.main()
