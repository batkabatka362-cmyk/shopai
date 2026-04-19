"""Conflict resolver tests — pick between two rules."""
from __future__ import annotations

import time
import unittest

from core.brain import conflict_resolver as cr


class TestSuccessRate(unittest.TestCase):
    def test_high_success_wins(self) -> None:
        a = {"id": "A", "fires": 20, "wins": 18, "provenance": "mined"}
        b = {"id": "B", "fires": 20, "wins": 4, "provenance": "mined"}
        res = cr.resolve(a, b)
        self.assertEqual(res.status, "resolved")
        self.assertEqual(res.winner_id, "A")


class TestProvenance(unittest.TestCase):
    def test_owner_demo_beats_mined(self) -> None:
        now = time.time()
        a = {"id": "A", "provenance": "owner_demo",
             "fires": 5, "wins": 3, "last_seen": now}
        b = {"id": "B", "provenance": "mined",
             "fires": 5, "wins": 3, "last_seen": now}
        res = cr.resolve(a, b)
        self.assertEqual(res.winner_id, "A")


class TestRecency(unittest.TestCase):
    def test_fresh_beats_stale(self) -> None:
        now = time.time()
        a = {"id": "A", "fires": 10, "wins": 5,
             "last_seen": now - 1 * 86_400}
        b = {"id": "B", "fires": 10, "wins": 5,
             "last_seen": now - 120 * 86_400}
        res = cr.resolve(a, b, now_ref=now)
        self.assertEqual(res.winner_id, "A")


class TestOwnerFeedback(unittest.TestCase):
    def test_upvotes_beat_downvotes(self) -> None:
        a = {"id": "A", "up_votes": 8, "down_votes": 1,
             "fires": 10, "wins": 5}
        b = {"id": "B", "up_votes": 1, "down_votes": 8,
             "fires": 10, "wins": 5}
        res = cr.resolve(a, b)
        self.assertEqual(res.winner_id, "A")


class TestHeightPreference(unittest.TestCase):
    def test_specific_wins_when_coverage_hot(self) -> None:
        a = {"id": "A", "height": 0, "fires": 5, "wins": 3}
        b = {"id": "B", "height": 2, "fires": 5, "wins": 3}
        res = cr.resolve(a, b, context_coverage=1.0)
        self.assertEqual(res.winner_id, "A")

    def test_abstract_wins_when_coverage_cold(self) -> None:
        a = {"id": "A", "height": 0, "fires": 5, "wins": 3}
        b = {"id": "B", "height": 2, "fires": 5, "wins": 3}
        res = cr.resolve(a, b, context_coverage=0.0)
        self.assertEqual(res.winner_id, "B")


class TestTie(unittest.TestCase):
    def test_identical_rules_tie(self) -> None:
        a = {"id": "A", "fires": 10, "wins": 5, "provenance": "mined"}
        b = {"id": "B", "fires": 10, "wins": 5, "provenance": "mined"}
        res = cr.resolve(a, b)
        self.assertEqual(res.status, "tie")
        self.assertIsNone(res.winner_id)


class TestBatch(unittest.TestCase):
    def test_batch_resolve_returns_one_per_pair(self) -> None:
        pairs = [
            ({"id": "a", "fires": 20, "wins": 18,
              "provenance": "owner_demo"},
             {"id": "b", "fires": 20, "wins": 4,
              "provenance": "mined"}),
            ({"id": "c", "fires": 10, "wins": 5},
             {"id": "d", "fires": 10, "wins": 5}),
        ]
        results = cr.batch_resolve(pairs)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].status, "resolved")


class TestSignalsBreakdown(unittest.TestCase):
    def test_signal_names_present(self) -> None:
        a = {"id": "A", "fires": 20, "wins": 18,
             "provenance": "owner_demo"}
        b = {"id": "B", "fires": 20, "wins": 4,
             "provenance": "mined"}
        res = cr.resolve(a, b)
        names = [s.name for s in res.signals]
        self.assertIn("success_rate", names)
        self.assertIn("provenance", names)
        self.assertIn("recency", names)


if __name__ == "__main__":
    unittest.main()
