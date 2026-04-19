"""Attention filter tests."""
from __future__ import annotations

import time
import unittest

from core.brain import attention_filter as af


class TestConfig(unittest.TestCase):
    def test_bad_half_life_raises(self) -> None:
        with self.assertRaises(ValueError):
            af.AttentionFilter(half_life_s=0)

    def test_bad_novelty_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            af.AttentionFilter(novelty_window=0)

    def test_weights_normalised(self) -> None:
        f = af.AttentionFilter(weights={"stakes": 2.0, "urgency": 2.0})
        total = sum(f._weights.values())
        self.assertAlmostEqual(total, 1.0)


class TestRecency(unittest.TestCase):
    def test_recent_scores_high(self) -> None:
        f = af.AttentionFilter(half_life_s=1.0)
        r_fresh = f._recency(ts=time.time(), now=time.time())
        r_old = f._recency(ts=time.time() - 10, now=time.time())
        self.assertGreater(r_fresh, r_old)

    def test_exactly_one_half_life_is_half(self) -> None:
        f = af.AttentionFilter(half_life_s=100.0)
        now = 1000.0
        r = f._recency(ts=now - 100.0, now=now)
        self.assertAlmostEqual(r, 0.5)


class TestNovelty(unittest.TestCase):
    def test_unseen_kind_full(self) -> None:
        f = af.AttentionFilter()
        self.assertEqual(f._novelty("anything"), 1.0)

    def test_repeated_kind_decays(self) -> None:
        f = af.AttentionFilter()
        for _ in range(20):
            f.observe("order")
        novel_score = f._novelty("order")
        self.assertLess(novel_score, 1.0)


class TestStakes(unittest.TestCase):
    def test_stakes_clamped(self) -> None:
        f = af.AttentionFilter()
        self.assertEqual(f._stakes({"stakes": -1}), 0.0)
        self.assertEqual(f._stakes({"stakes": 2.0}), 1.0)
        self.assertEqual(f._stakes({}), 0.0)

    def test_invalid_stakes_zero(self) -> None:
        f = af.AttentionFilter()
        self.assertEqual(f._stakes({"stakes": "hello"}), 0.0)


class TestSurprise(unittest.TestCase):
    def test_matching_prediction_zero_surprise(self) -> None:
        f = af.AttentionFilter()
        self.assertEqual(
            f._surprise({"predicted": 0.5, "actual": 0.5}),
            0.0,
        )

    def test_divergent_prediction_high_surprise(self) -> None:
        f = af.AttentionFilter()
        s = f._surprise({"predicted": 0.1, "actual": 0.9})
        self.assertGreater(s, 0.5)

    def test_missing_components_zero(self) -> None:
        f = af.AttentionFilter()
        self.assertEqual(f._surprise({"predicted": 0.5}), 0.0)


class TestUrgency(unittest.TestCase):
    def test_explicit_urgent(self) -> None:
        f = af.AttentionFilter()
        self.assertEqual(f._urgency({"urgent": True}), 1.0)

    def test_owner_routed(self) -> None:
        f = af.AttentionFilter()
        self.assertEqual(f._urgency({"owner_routed": True}), 0.8)


class TestScore(unittest.TestCase):
    def test_score_combines_components(self) -> None:
        f = af.AttentionFilter()
        s = f.score({
            "id": "o1", "kind": "order",
            "stakes": 0.9, "urgent": True,
            "predicted": 0.2, "actual": 0.9,
        })
        self.assertGreater(s.score, 0.5)

    def test_id_fallback_hash(self) -> None:
        f = af.AttentionFilter()
        s = f.score({"kind": "x"})
        self.assertEqual(len(s.event_id), 12)

    def test_unknown_kind_safe(self) -> None:
        f = af.AttentionFilter()
        s = f.score({})
        self.assertGreaterEqual(s.score, 0.0)


class TestTopK(unittest.TestCase):
    def test_picks_top_by_score(self) -> None:
        f = af.AttentionFilter()
        now = time.time()
        events = [
            {"id": "boring", "kind": "ping", "ts": now, "stakes": 0.1},
            {"id": "big",    "kind": "big",  "ts": now, "stakes": 0.9,
             "urgent": True, "predicted": 0.1, "actual": 0.9},
            {"id": "meh",    "kind": "ping", "ts": now, "stakes": 0.3},
        ]
        top = f.top_k(events, k=2)
        self.assertEqual(top[0].event_id, "big")

    def test_k_respected(self) -> None:
        f = af.AttentionFilter()
        events = [{"id": str(i), "kind": "x"} for i in range(10)]
        top = f.top_k(events, k=3)
        self.assertEqual(len(top), 3)

    def test_history_updated(self) -> None:
        f = af.AttentionFilter()
        events = [{"id": "1", "kind": "rare"}]
        f.top_k(events)
        # Second call with same kind should score lower novelty now
        before = f._novelty("rare")
        f.top_k(events)
        after = f._novelty("rare")
        self.assertLess(after, before)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        f = af.AttentionFilter()
        for _ in range(3):
            f.observe("order")
        s = f.stats()
        self.assertIn("weights", s)
        self.assertIn("seen_kinds", s)
        self.assertEqual(s["seen_kinds"], 1)


class TestDict(unittest.TestCase):
    def test_score_serialises(self) -> None:
        f = af.AttentionFilter()
        s = f.score({"id": "x", "kind": "y", "stakes": 0.5})
        d = s.as_dict()
        self.assertIn("score", d)
        self.assertIn("components", d)


if __name__ == "__main__":
    unittest.main()
