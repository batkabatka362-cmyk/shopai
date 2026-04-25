"""Tests for core.memory.consolidator — Track 2."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory.consolidator import (
    Concept,
    Episode,
    MemoryConsolidator,
    Procedure,
    get_consolidator,
    reset_consolidator_for_tests,
)


def _build(tmp, *, now_list=None, **kw):
    defaults = dict(
        db_path=Path(tmp) / "m.db",
        min_episodes_for_concept=3,
        lookback_s=10_000.0,
        min_concept_refs_for_procedure=3,
        min_success_rate=0.60,
        stale_after_s=1000.0,
        cold_floor=0.2,
    )
    defaults.update(kw)
    if now_list is not None:
        it = iter(now_list)
        defaults["now_fn"] = lambda: next(it, 99999.0)
    return MemoryConsolidator(**defaults)


class TestConfig(unittest.TestCase):
    def test_bad_min_episodes(self):
        with self.assertRaises(ValueError):
            MemoryConsolidator(
                min_episodes_for_concept=0,
            )

    def test_bad_success_rate(self):
        with self.assertRaises(ValueError):
            MemoryConsolidator(min_success_rate=1.5)

    def test_bad_stale_after(self):
        with self.assertRaises(ValueError):
            MemoryConsolidator(stale_after_s=0)


class TestSignature(unittest.TestCase):
    def test_deterministic(self):
        a = MemoryConsolidator.signature_of(
            niche="pet", kpi="roas",
        )
        b = MemoryConsolidator.signature_of(
            niche="pet", kpi="roas",
        )
        self.assertEqual(a, b)

    def test_order_independent(self):
        a = MemoryConsolidator.signature_of(
            niche="pet", kpi="roas",
        )
        b = MemoryConsolidator.signature_of(
            kpi="roas", niche="pet",
        )
        self.assertEqual(a, b)


class TestEpisodes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.c = _build(self._tmp.name)

    def tearDown(self):
        self.c.close()
        self._tmp.cleanup()

    def test_record_episode_blank_signature(self):
        with self.assertRaises(ValueError):
            self.c.record_episode(
                signature="", outcome_ok=True,
            )

    def test_record_episode_stores(self):
        ep = self.c.record_episode(
            signature="sig-1",
            outcome_ok=True,
            payload={"note": "first"},
        )
        self.assertEqual(ep.signature, "sig-1")
        self.assertTrue(ep.outcome_ok)


class TestConsolidation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.c = _build(self._tmp.name)

    def tearDown(self):
        self.c.close()
        self._tmp.cleanup()

    def test_3_episodes_same_sig_promoted(self):
        for _ in range(3):
            self.c.record_episode(
                signature="kill_at_roas_low",
                outcome_ok=False,
            )
        report = self.c.consolidate()
        self.assertEqual(report.concepts_promoted, 1)
        concept = self.c.get_concept("kill_at_roas_low")
        self.assertEqual(concept.evidence_count, 3)

    def test_below_threshold_stays_episodic(self):
        for _ in range(2):
            self.c.record_episode(
                signature="x", outcome_ok=True,
            )
        report = self.c.consolidate()
        self.assertEqual(report.concepts_promoted, 0)

    def test_consolidate_is_idempotent(self):
        # Second call shouldn't re-consolidate already seen
        for _ in range(3):
            self.c.record_episode(
                signature="x", outcome_ok=True,
            )
        self.c.consolidate()
        report2 = self.c.consolidate()
        self.assertEqual(report2.concepts_promoted, 0)

    def test_reference_concept_updates_counters(self):
        for _ in range(3):
            self.c.record_episode(
                signature="x", outcome_ok=True,
            )
        self.c.consolidate()
        concept = self.c.reference_concept(
            "x", success=True,
        )
        self.assertGreaterEqual(concept.refs, 1)

    def test_reference_missing_concept(self):
        r = self.c.reference_concept(
            "never-seen", success=True,
        )
        self.assertIsNone(r)

    def test_concept_to_procedure_promotion(self):
        # 3 episodes form a concept
        for _ in range(3):
            self.c.record_episode(
                signature="replay_at_mid_roas",
                outcome_ok=True,
            )
        self.c.consolidate()
        # Reference 3 times with success → promote to procedure
        for _ in range(3):
            self.c.reference_concept(
                "replay_at_mid_roas", success=True,
            )
        report = self.c.consolidate()
        self.assertEqual(report.procedures_promoted, 1)
        procs = self.c.procedures()
        self.assertEqual(procs[0].signature, "replay_at_mid_roas")

    def test_low_success_rate_blocks_procedure(self):
        for _ in range(3):
            self.c.record_episode(
                signature="risky", outcome_ok=True,
            )
        self.c.consolidate()
        for _ in range(3):
            self.c.reference_concept(
                "risky", success=False,
            )
        report = self.c.consolidate()
        self.assertEqual(report.procedures_promoted, 0)


class TestStaleness(unittest.TestCase):
    def test_stale_concept_decays(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            # record_episode + consolidate each call now_fn
            # exactly once, so 5 timestamps cover: 3 episodes
            # + 1 first-consolidate (promotes concept, sets
            # last_access=1003) + 1 second-consolidate at
            # t=5000 (elapsed 3997s > stale_after=1000 → decay)
            c = _build(tmp.name, now_list=[
                1000.0, 1001.0, 1002.0,   # 3 episodes
                1003.0,                     # 1st consolidate
                5000.0,                     # 2nd consolidate
            ])
            for _ in range(3):
                c.record_episode(
                    signature="s", outcome_ok=True,
                )
            c.consolidate()
            report = c.consolidate()
            self.assertEqual(report.stale_decayed, 1)
            c.close()
        finally:
            tmp.cleanup()

    def test_stale_below_floor_archived(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            # 3 episodes + 1 consolidate + 5 staleness sweeps.
            # Each sweep advances ≥ stale_after so priority
            # halves each time: 1.0 → 0.5 → 0.25 → 0.125 (<
            # cold_floor 0.2) → archived.
            now_list = [1000.0, 1001.0, 1002.0, 1003.0]
            for i in range(1, 7):
                now_list.append(1003.0 + i * 2000.0)
            c = _build(
                tmp.name, now_list=now_list,
                stale_after_s=100.0,
                cold_floor=0.2,
            )
            for _ in range(3):
                c.record_episode(
                    signature="s", outcome_ok=True,
                )
            c.consolidate()
            for _ in range(6):
                c.consolidate()
            s = c.stats()
            self.assertGreaterEqual(s["cold_archive"], 1)
            c.close()
        finally:
            tmp.cleanup()


class TestQueries(unittest.TestCase):
    def test_concepts_sorted_by_priority_evidence(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            c = _build(tmp.name)
            for _ in range(3):
                c.record_episode(
                    signature="a", outcome_ok=True,
                )
            for _ in range(5):
                c.record_episode(
                    signature="b", outcome_ok=True,
                )
            c.consolidate()
            out = c.concepts()
            self.assertEqual(out[0].signature, "b")
            c.close()
        finally:
            tmp.cleanup()

    def test_stats_shape(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            c = _build(tmp.name)
            s = c.stats()
            for key in (
                "episodes", "concepts", "procedures",
                "cold_archive",
                "min_episodes_for_concept",
            ):
                self.assertIn(key, s)
            c.close()
        finally:
            tmp.cleanup()


class TestSingleton(unittest.TestCase):
    def test_singleton_reused(self):
        reset_consolidator_for_tests()
        try:
            a = get_consolidator()
            b = get_consolidator()
            self.assertIs(a, b)
        finally:
            reset_consolidator_for_tests()


class TestDict(unittest.TestCase):
    def test_episode_dict(self):
        e = Episode(
            episode_id="e", signature="s",
            outcome_ok=True,
        )
        self.assertIn("episode_id", e.as_dict())

    def test_concept_dict(self):
        c = Concept(
            concept_id="c", signature="s",
            evidence_count=3,
        )
        d = c.as_dict()
        self.assertIn("success_rate", d)

    def test_procedure_dict(self):
        p = Procedure(
            procedure_id="p", signature="s",
            from_concept="c",
        )
        self.assertIn("refs", p.as_dict())


if __name__ == "__main__":
    unittest.main()
