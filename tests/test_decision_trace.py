"""Decision trace — evidence DAG math + persistence tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.brain import decision_trace as dt


class TestCite(unittest.TestCase):
    def test_cite_clamps_weight(self) -> None:
        t = dt.Trace(goal="x")
        e = t.cite(kind="memory", ref_id=1, weight=5.0)
        self.assertEqual(e.weight, 1.0)
        e = t.cite(kind="memory", ref_id=2, weight=-0.5)
        self.assertEqual(e.weight, 0.0)

    def test_note_truncated(self) -> None:
        t = dt.Trace(goal="x")
        e = t.cite(kind="memory", ref_id=1, weight=0.5, note="x" * 500)
        self.assertEqual(len(e.note), 400)


class TestNormalise(unittest.TestCase):
    def test_normalise_sums_to_one(self) -> None:
        t = dt.Trace(goal="x")
        t.cite(kind="memory", ref_id=1, weight=0.2)
        t.cite(kind="fact", ref_id="r.t", weight=0.3)
        t.cite(kind="simulation", ref_id="s1", weight=0.5)
        t.normalise_weights()
        total = sum(e.weight for e in t.evidence)
        self.assertAlmostEqual(total, 1.0)

    def test_normalise_zero_total_noop(self) -> None:
        t = dt.Trace(goal="x")
        t.cite(kind="memory", ref_id=1, weight=0)
        t.normalise_weights()
        self.assertEqual(t.evidence[0].weight, 0.0)


class TestConclude(unittest.TestCase):
    def test_conclude_sets_fields(self) -> None:
        t = dt.Trace(goal="kill launch")
        t.conclude(verdict="kill", confidence=0.85, narrative="because ROAS")
        self.assertEqual(t.verdict, "kill")
        self.assertAlmostEqual(t.confidence, 0.85)
        self.assertGreater(t.concluded_at, 0)

    def test_confidence_clamped(self) -> None:
        t = dt.Trace(goal="x")
        t.conclude(verdict="kill", confidence=2.5)
        self.assertEqual(t.confidence, 1.0)


class TestTopEvidence(unittest.TestCase):
    def test_sorts_by_weight_descending(self) -> None:
        t = dt.Trace(goal="x")
        t.cite(kind="memory", ref_id=1, weight=0.1)
        t.cite(kind="memory", ref_id=2, weight=0.6)
        t.cite(kind="memory", ref_id=3, weight=0.3)
        top = t.top_evidence(k=2)
        self.assertEqual(top[0].ref_id, "2")
        self.assertEqual(top[1].ref_id, "3")


class TestPersist(unittest.TestCase):
    def test_persist_swallows_exception(self) -> None:
        t = dt.Trace(goal="x")
        t.cite(kind="memory", ref_id=1, weight=0.5)
        t.conclude(verdict="kill", confidence=0.5)
        with patch("core.memory.intelligence.get_memory_intelligence",
                   side_effect=RuntimeError("boom")):
            mid = t.persist()
        self.assertIsNone(mid)

    def test_persist_returns_id(self) -> None:
        t = dt.Trace(goal="x")
        t.conclude(verdict="kill", confidence=0.5)
        from unittest.mock import MagicMock
        fake_mi = MagicMock()
        fake_mi.create.return_value = 99
        with patch("core.memory.intelligence.get_memory_intelligence",
                   return_value=fake_mi):
            mid = t.persist()
        self.assertEqual(mid, 99)


class TestExplain(unittest.TestCase):
    def test_explain_missing_trace(self) -> None:
        with patch.object(dt, "get_trace", return_value=None):
            out = dt.explain("missing")
        self.assertIn("no trace", out)

    def test_explain_renders_top_evidence(self) -> None:
        fake_trace = {
            "verdict": "kill",
            "confidence": 0.8,
            "goal": "kill the loser",
            "narrative": "ROAS too low",
            "evidence": [
                {"kind": "memory", "ref_id": "1", "weight": 0.5, "note": "prior fail"},
                {"kind": "fact", "ref_id": "roas.kill_threshold",
                 "weight": 0.3, "note": "threshold 1.5"},
                {"kind": "simulation", "ref_id": "s1", "weight": 0.2, "note": "MC net saved"},
            ],
        }
        with patch.object(dt, "get_trace", return_value=fake_trace):
            out = dt.explain("abc", top_k=2)
        self.assertIn("kill", out)
        self.assertIn("memory", out)
        self.assertIn("0.50", out)


if __name__ == "__main__":
    unittest.main()
