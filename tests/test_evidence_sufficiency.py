"""Evidence sufficiency tests."""
from __future__ import annotations

import time
import unittest

from core.brain import evidence_sufficiency as es


class TestEmpty(unittest.TestCase):
    def test_no_evidence_abstains(self) -> None:
        r = es.check([])
        self.assertEqual(r.verdict, "abstain")
        self.assertEqual(r.overall, 0.0)
        self.assertEqual(r.weakest_dimension, "coverage")


class TestThresholds(unittest.TestCase):
    def test_strong_evidence_decides(self) -> None:
        now = time.time()
        facts = [
            es.EvidenceFact("policy", 1.0, now),
            es.EvidenceFact("reward", 0.8, now),
            es.EvidenceFact("search", 0.7, now),
            es.EvidenceFact("rule", 0.6, now),
        ]
        r = es.check(facts)
        self.assertEqual(r.verdict, "decide")

    def test_moderate_evidence_gathers(self) -> None:
        now = time.time()
        facts = [
            es.EvidenceFact("policy", 0.4, now),
            es.EvidenceFact("policy", 0.4, now),
        ]
        r = es.check(facts, min_sources=4)
        self.assertIn(r.verdict, ("gather", "abstain"))

    def test_single_source_low_diversity(self) -> None:
        now = time.time()
        facts = [es.EvidenceFact("policy", 0.6, now) for _ in range(10)]
        r = es.check(facts)
        self.assertEqual(r.diversity_score, 0.0)


class TestCoverage(unittest.TestCase):
    def test_meets_min_sources(self) -> None:
        now = time.time()
        facts = [
            es.EvidenceFact("a", 0.5, now),
            es.EvidenceFact("b", 0.5, now),
            es.EvidenceFact("c", 0.5, now),
        ]
        r = es.check(facts, min_sources=3)
        self.assertEqual(r.coverage_score, 1.0)

    def test_fewer_than_min(self) -> None:
        facts = [es.EvidenceFact("a", 0.5)]
        r = es.check(facts, min_sources=4)
        self.assertAlmostEqual(r.coverage_score, 0.25)


class TestVolume(unittest.TestCase):
    def test_saturates_at_min_volume(self) -> None:
        now = time.time()
        facts = [es.EvidenceFact("a", 2.0, now)]   # weight = 2 hits min=2
        r = es.check(facts, min_volume=2.0)
        self.assertEqual(r.volume_score, 1.0)

    def test_below_min_volume(self) -> None:
        facts = [es.EvidenceFact("a", 0.5)]
        r = es.check(facts, min_volume=5.0)
        self.assertLess(r.volume_score, 0.5)


class TestRecency(unittest.TestCase):
    def test_recent_fact_full_score(self) -> None:
        now = time.time()
        facts = [es.EvidenceFact("a", 0.5, now)]
        r = es.check(facts, recency_window_s=3600)
        self.assertEqual(r.recency_score, 1.0)

    def test_stale_facts_penalised(self) -> None:
        now = time.time()
        facts = [
            es.EvidenceFact("a", 0.5, now - 10 * 86_400),
            es.EvidenceFact("b", 0.5, now - 10 * 86_400),
        ]
        r = es.check(facts, recency_window_s=3600)
        self.assertLess(r.recency_score, 0.5)

    def test_missing_ts_neutral(self) -> None:
        facts = [
            es.EvidenceFact("a", 0.5, 0.0),
            es.EvidenceFact("b", 0.5, 0.0),
        ]
        r = es.check(facts)
        # Missing ts → 0.5 neutral
        self.assertAlmostEqual(r.recency_score, 0.5)


class TestDiversity(unittest.TestCase):
    def test_even_distribution_high_diversity(self) -> None:
        now = time.time()
        facts = [
            es.EvidenceFact("a", 0.5, now),
            es.EvidenceFact("b", 0.5, now),
            es.EvidenceFact("c", 0.5, now),
        ]
        r = es.check(facts)
        self.assertAlmostEqual(r.diversity_score, 1.0, places=2)

    def test_skewed_distribution_lower_diversity(self) -> None:
        now = time.time()
        facts = [es.EvidenceFact("a", 0.5, now) for _ in range(9)]
        facts.append(es.EvidenceFact("b", 0.5, now))
        r = es.check(facts)
        self.assertLess(r.diversity_score, 0.9)


class TestDictFacts(unittest.TestCase):
    def test_dict_coerced(self) -> None:
        now = time.time()
        facts = [
            {"source": "a", "weight": 0.5, "ts": now},
            {"source": "b", "weight": 0.5, "ts": now},
            {"source": "c", "weight": 0.5, "ts": now},
        ]
        r = es.check(facts)
        self.assertIn(r.verdict, ("decide", "gather", "abstain"))


class TestReport(unittest.TestCase):
    def test_as_dict(self) -> None:
        r = es.check([es.EvidenceFact("a", 0.5, time.time())])
        d = r.as_dict()
        for key in (
            "verdict", "overall", "coverage_score", "volume_score",
            "recency_score", "diversity_score", "weakest_dimension",
            "n_facts", "sources",
        ):
            self.assertIn(key, d)

    def test_weakest_dimension_identified(self) -> None:
        now = time.time()
        facts = [
            es.EvidenceFact("a", 2.0, now),
            es.EvidenceFact("b", 2.0, now),
            es.EvidenceFact("c", 2.0, now),
        ]
        r = es.check(facts, min_sources=10, min_volume=1.0)
        self.assertEqual(r.weakest_dimension, "coverage")


if __name__ == "__main__":
    unittest.main()
