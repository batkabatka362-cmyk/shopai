"""Preference elicitation tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import preference_elicitation as pe


class TestBuild(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.e = pe.PreferenceElicitation(Path(self._tmp.name) / "p.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pairwise_query_stored_as_pending(self) -> None:
        q = self.e.build_pairwise_query([
            pe.Option(id="a", label="A", features={"tone": "luxury"}),
            pe.Option(id="b", label="B", features={"tone": "friendly"}),
        ], rationale="coin flip")
        self.assertEqual(q.status, "pending")
        self.assertEqual(len(q.options), 2)
        self.assertEqual(self.e.get(q.id).rationale, "coin flip")

    def test_single_option_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.e.build_pairwise_query([pe.Option(id="a", label="A")])

    def test_build_accepts_dicts(self) -> None:
        q = self.e.build_pairwise_query([
            {"id": "x", "label": "X"},
            {"id": "y", "label": "Y"},
        ])
        self.assertEqual(len(q.options), 2)


class TestRecordAnswer(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.folded: list[tuple] = []
        self.e = pe.PreferenceElicitation(
            Path(self._tmp.name) / "p.db",
            reward_recorder=lambda feat, w: self.folded.append((feat, w)),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_answer_marks_answered(self) -> None:
        q = self.e.build_pairwise_query([
            pe.Option(id="a", label="A"),
            pe.Option(id="b", label="B"),
        ])
        result = self.e.record_answer(q.id, "a")
        self.assertEqual(result.status, "answered")
        self.assertEqual(result.answer, "a")

    def test_answer_feeds_reward(self) -> None:
        q = self.e.build_pairwise_query([
            pe.Option(id="a", label="A", features={"tone": "luxury"}),
            pe.Option(id="b", label="B", features={"tone": "friendly"}),
        ])
        self.e.record_answer(q.id, "a", weight=2.0)
        # Chose A → A fed with +2, B with -1
        a_fold = next(
            f for f, w in self.folded if f == {"tone": "luxury"}
        )
        self.assertIsNotNone(a_fold)

    def test_invalid_option_raises(self) -> None:
        q = self.e.build_pairwise_query([
            pe.Option(id="a", label="A"),
            pe.Option(id="b", label="B"),
        ])
        with self.assertRaises(ValueError):
            self.e.record_answer(q.id, "nonexistent")

    def test_unknown_query_returns_none(self) -> None:
        self.assertIsNone(self.e.record_answer("missing", "a"))


class TestPendingAndRecent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.e = pe.PreferenceElicitation(Path(self._tmp.name) / "p.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pending_lists_unanswered(self) -> None:
        q1 = self.e.build_pairwise_query([
            pe.Option(id="a", label="A"), pe.Option(id="b", label="B"),
        ])
        q2 = self.e.build_pairwise_query([
            pe.Option(id="c", label="C"), pe.Option(id="d", label="D"),
        ])
        self.e.record_answer(q1.id, "a")
        pending = self.e.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].id, q2.id)

    def test_recent_answers(self) -> None:
        q = self.e.build_pairwise_query([
            pe.Option(id="a", label="A"), pe.Option(id="b", label="B"),
        ])
        self.e.record_answer(q.id, "b")
        recent = self.e.recent_answers()
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].answer, "b")


class TestTriage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.e = pe.PreferenceElicitation(Path(self._tmp.name) / "p.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_close_decisions_yield_query(self) -> None:
        close = [
            {
                "options": [
                    {"id": "a", "label": "A", "score": 0.81},
                    {"id": "b", "label": "B", "score": 0.80},
                ],
                "rationale": "near tie",
            },
            {
                "options": [
                    {"id": "c", "label": "C", "score": 0.95},
                    {"id": "d", "label": "D", "score": 0.60},
                ],
                "rationale": "decisive",
            },
        ]
        queries = self.e.triage(close, margin_threshold=0.05)
        self.assertEqual(len(queries), 1)
        self.assertIn("tie", queries[0].rationale)

    def test_single_option_skipped(self) -> None:
        queries = self.e.triage([
            {"options": [{"id": "a", "label": "A", "score": 0.9}]},
        ])
        self.assertEqual(queries, [])


if __name__ == "__main__":
    unittest.main()
