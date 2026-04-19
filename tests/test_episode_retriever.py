"""Episode retriever tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.memory import episode_retriever as er


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.r = er.EpisodeRetriever(Path(self._tmp.name) / "e.db")

    def tearDown(self) -> None:
        self.r.close()
        self._tmp.cleanup()

    def test_record_returns_episode(self) -> None:
        ep = self.r.record(
            {"niche": "audio"},
            tags=("launch",),
            outcome_sign="win",
        )
        self.assertEqual(ep.tags, ("launch",))
        self.assertEqual(ep.outcome_sign, "win")

    def test_invalid_outcome_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.record({}, outcome_sign="unexpected")  # type: ignore

    def test_timeline_accepts_dict_or_event(self) -> None:
        ep = self.r.record(
            {"x": 1},
            timeline=[
                er.EpisodeEvent(kind="phase", summary="ingest ok"),
                {"kind": "outcome", "summary": "win", "ts": 5.0},
            ],
        )
        self.assertEqual(len(ep.timeline), 2)
        self.assertEqual(ep.timeline[1].ts, 5.0)

    def test_invalid_half_life_raises(self) -> None:
        with self.assertRaises(ValueError):
            er.EpisodeRetriever(half_life_days=0)


class TestSimilarity(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.r = er.EpisodeRetriever(Path(self._tmp.name) / "e.db")

    def tearDown(self) -> None:
        self.r.close()
        self._tmp.cleanup()

    def test_exact_match_high_score(self) -> None:
        self.r.record({"niche": "audio", "price": 30.0})
        self.r.record({"niche": "fashion", "price": 80.0})
        matches = self.r.find_similar({"niche": "audio", "price": 30.0})
        self.assertEqual(matches[0].episode.situation["niche"], "audio")
        self.assertGreater(matches[0].similarity, 0.8)

    def test_empty_retriever_returns_empty(self) -> None:
        self.assertEqual(
            self.r.find_similar({"niche": "audio"}), [],
        )

    def test_tag_filter_excludes(self) -> None:
        self.r.record({"niche": "audio"}, tags=("launch",))
        self.r.record({"niche": "audio"}, tags=("refund",))
        matches = self.r.find_similar(
            {"niche": "audio"}, tags=("launch",),
        )
        self.assertEqual(len(matches), 1)
        self.assertIn("launch", matches[0].episode.tags)

    def test_outcome_filter(self) -> None:
        self.r.record({"x": 1}, outcome_sign="win")
        self.r.record({"x": 1}, outcome_sign="loss")
        matches = self.r.find_similar({"x": 1}, outcome_sign="win")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].episode.outcome_sign, "win")

    def test_score_combines_similarity_and_recency(self) -> None:
        self.r.record({"niche": "audio"})
        match = self.r.find_similar({"niche": "audio"})[0]
        # Fresh record → recency weight near 1.0
        self.assertGreater(match.recency_weight, 0.99)


class TestRecencyDecay(unittest.TestCase):
    def test_old_episode_discounted(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        r = er.EpisodeRetriever(
            Path(tmp.name) / "e.db",
            half_life_days=1.0,
        )
        # Record two identical situations, backdate one far in the past
        ep_old = r.record({"niche": "audio"})
        ep_new = r.record({"niche": "audio"})
        # Force ep_old.ts to 10 days ago
        ep_old.ts = time.time() - 10 * 86_400.0
        r._episodes[ep_old.id] = ep_old
        matches = r.find_similar({"niche": "audio"}, k=2)
        # Fresh episode scored higher
        self.assertEqual(matches[0].episode.id, ep_new.id)
        r.close()
        tmp.cleanup()


class TestRecent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.r = er.EpisodeRetriever(Path(self._tmp.name) / "e.db")

    def tearDown(self) -> None:
        self.r.close()
        self._tmp.cleanup()

    def test_most_recent_first(self) -> None:
        for i in range(5):
            self.r.record({"i": i})
        recent = self.r.recent(k=3)
        # Latest record has i=4
        self.assertEqual(recent[0].situation["i"], 4)

    def test_k_limit_respected(self) -> None:
        for i in range(10):
            self.r.record({"i": i})
        self.assertEqual(len(self.r.recent(k=3)), 3)


class TestByOutcome(unittest.TestCase):
    def test_filter(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        r = er.EpisodeRetriever(Path(tmp.name) / "e.db")
        r.record({"x": 1}, outcome_sign="win")
        r.record({"x": 2}, outcome_sign="loss")
        wins = r.by_outcome("win")
        self.assertEqual(len(wins), 1)
        self.assertEqual(wins[0].outcome_sign, "win")
        r.close()
        tmp.cleanup()


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "e.db"
        first = er.EpisodeRetriever(path)
        first.record(
            {"niche": "audio"},
            timeline=[er.EpisodeEvent("phase", "ingest ok")],
            tags=("launch",),
            outcome_sign="win",
        )
        first.close()
        second = er.EpisodeRetriever(path)
        recent = second.recent()
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].tags, ("launch",))
        self.assertEqual(len(recent[0].timeline), 1)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        r = er.EpisodeRetriever(Path(tmp.name) / "e.db")
        r.record({"x": 1}, outcome_sign="win", tags=("a", "b"))
        r.record({"x": 2}, outcome_sign="loss", tags=("a",))
        s = r.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_outcome"]["win"], 1)
        self.assertEqual(s["distinct_tags"], 2)
        r.close()
        tmp.cleanup()


class TestPrune(unittest.TestCase):
    def test_prune_old(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        r = er.EpisodeRetriever(Path(tmp.name) / "e.db")
        ep = r.record({"x": 1})
        ep.ts = 100.0
        r._episodes[ep.id] = ep
        r.prune_before(200.0)
        self.assertEqual(r.stats()["total"], 0)
        r.close()
        tmp.cleanup()


class TestDict(unittest.TestCase):
    def test_episode_and_match_serialise(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        r = er.EpisodeRetriever(Path(tmp.name) / "e.db")
        r.record(
            {"x": 1},
            timeline=[er.EpisodeEvent("phase", "ok")],
            tags=("t",),
        )
        ep_dict = r.recent()[0].as_dict()
        self.assertIn("timeline", ep_dict)
        match = r.find_similar({"x": 1})[0]
        self.assertIn("similarity", match.as_dict())
        r.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
