"""Episode summariser tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory import episode_summarizer as es


class TestSummarise(unittest.TestCase):
    def setUp(self) -> None:
        self.s = es.EpisodeSummariser()

    def test_blank_title_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.s.summarise(
                title_hint="", winning_action="x",
            )

    def test_blank_action_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.s.summarise(
                title_hint="t", winning_action="",
            )

    def test_happy_path(self) -> None:
        summary = self.s.summarise(
            title_hint="launch $20/day ad",
            situation={"niche": "pet", "aov": "40-60"},
            winning_action="set budget $20/day Meta",
            alternatives=["wait one more day"],
            outcome_score=0.8,
            lesson="early scale outpaces waiting",
            evidence_keys=["mem:1", "mem:2"],
        )
        self.assertEqual(summary.outcome, "win")
        self.assertEqual(len(summary.situation_terms), 2)

    def test_loss_classification(self) -> None:
        summary = self.s.summarise(
            title_hint="scaled too early",
            winning_action="raised budget 3x",
            outcome_score=0.1,
        )
        self.assertEqual(summary.outcome, "loss")

    def test_pending_no_score(self) -> None:
        summary = self.s.summarise(
            title_hint="still running",
            winning_action="launched ad",
        )
        self.assertEqual(summary.outcome, "pending")

    def test_alternatives_capped(self) -> None:
        summary = self.s.summarise(
            title_hint="t",
            winning_action="a",
            alternatives=["a1", "a2", "a3", "a4", "a5"],
        )
        self.assertEqual(len(summary.alternatives), 3)

    def test_long_title_truncated(self) -> None:
        long_hint = "x" * 200
        summary = self.s.summarise(
            title_hint=long_hint, winning_action="a",
        )
        self.assertLess(len(summary.title), 100)


class TestParagraph(unittest.TestCase):
    def test_paragraph_includes_parts(self) -> None:
        s = es.EpisodeSummariser()
        summary = s.summarise(
            title_hint="ad launch",
            situation={"niche": "pet"},
            winning_action="set budget $20",
            alternatives=["wait"],
            outcome_score=0.8,
            lesson="early is better",
        )
        p = summary.as_paragraph()
        self.assertIn("ad launch", p)
        self.assertIn("niche=pet", p)
        self.assertIn("set budget", p)
        self.assertIn("Declined:", p)
        self.assertIn("Lesson:", p)


class TestQueries(unittest.TestCase):
    def setUp(self) -> None:
        self.s = es.EpisodeSummariser()
        self.win = self.s.summarise(
            title_hint="w",
            winning_action="a", outcome_score=0.9,
        )
        self.loss = self.s.summarise(
            title_hint="l",
            winning_action="a", outcome_score=0.1,
        )

    def test_get(self) -> None:
        self.assertIsNotNone(self.s.get(self.win.id))
        self.assertIsNone(self.s.get("nope"))

    def test_recent_newest_first(self) -> None:
        r = self.s.recent()
        self.assertEqual(r[0].id, self.loss.id)

    def test_wins_and_losses(self) -> None:
        self.assertEqual(len(self.s.wins()), 1)
        self.assertEqual(len(self.s.losses()), 1)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "e.db"
        first = es.EpisodeSummariser(path)
        first.summarise(
            title_hint="t",
            winning_action="a",
            outcome_score=0.9,
        )
        first.close()
        second = es.EpisodeSummariser(path)
        self.assertEqual(len(second.wins()), 1)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        s = es.EpisodeSummariser()
        s.summarise(
            title_hint="t",
            winning_action="a", outcome_score=0.9,
        )
        st = s.stats()
        self.assertEqual(st["total"], 1)
        self.assertEqual(st["by_outcome"]["win"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        s = es.EpisodeSummariser()
        s.summarise(
            title_hint="t", winning_action="a",
        )
        self.assertEqual(s.reset(), 1)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        s = es.EpisodeSummariser()
        summary = s.summarise(
            title_hint="t", winning_action="a",
        )
        d = summary.as_dict()
        self.assertIn("title", d)


if __name__ == "__main__":
    unittest.main()
