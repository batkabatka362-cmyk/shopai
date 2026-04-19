"""Explanation aggregator tests."""
from __future__ import annotations

import unittest

from core.brain import explanation_aggregator as ea


class TestBasicShape(unittest.TestCase):
    def test_empty_inputs_return_empty_sections(self) -> None:
        e = ea.aggregate(decision_id="d1")
        self.assertEqual(e.decision_id, "d1")
        self.assertEqual(e.highlights, [])
        titles = [s.title for s in e.sections]
        self.assertIn("Context", titles)
        self.assertIn("Decision", titles)

    def test_summary_carries_verdict(self) -> None:
        e = ea.aggregate(
            decision_id="d1", verdict="kill",
            confidence=0.72,
        )
        self.assertIn("kill", e.summary)
        self.assertIn("0.72", e.summary)


class TestHighlights(unittest.TestCase):
    def test_top_highlights_sorted_by_weight(self) -> None:
        e = ea.aggregate(
            decision_id="d1",
            evidence=[
                {"kind": "memory", "weight": 0.2, "note": "small"},
                {"kind": "memory", "weight": 0.9, "note": "big"},
                {"kind": "memory", "weight": 0.5, "note": "mid"},
            ],
        )
        self.assertEqual(len(e.highlights), 3)
        self.assertAlmostEqual(e.highlights[0].weight, 0.9)
        self.assertAlmostEqual(e.highlights[-1].weight, 0.2)

    def test_hard_ethics_violation_appears(self) -> None:
        e = ea.aggregate(
            decision_id="d1",
            violations=[{
                "rule": "no_deceptive_price_anchor",
                "severity": "hard",
                "reason": "compare too high",
            }],
        )
        sources = [h.source for h in e.highlights]
        self.assertTrue(any(s.startswith("ethics") for s in sources))

    def test_top_three_only(self) -> None:
        e = ea.aggregate(
            decision_id="d1",
            evidence=[
                {"kind": "x", "weight": i / 10, "note": f"e{i}"}
                for i in range(10)
            ],
        )
        self.assertEqual(len(e.highlights), 3)


class TestSections(unittest.TestCase):
    def test_policy_section_populated(self) -> None:
        e = ea.aggregate(
            decision_id="d1",
            policies=[
                {"name": "audio_kill", "fit": 0.9, "score": 0.8},
            ],
        )
        pol = next(s for s in e.sections if s.title == "Policies")
        self.assertTrue(any("audio_kill" in line for line in pol.body))

    def test_reward_section_populated(self) -> None:
        e = ea.aggregate(
            decision_id="d1",
            reward_contributions=[
                {"feature": "niche", "value": "audio", "llr": 0.7},
            ],
        )
        rew = next(
            s for s in e.sections if s.title == "Reward model"
        )
        self.assertTrue(any("niche=audio" in line for line in rew.body))

    def test_monologue_section_conditional(self) -> None:
        e = ea.aggregate(
            decision_id="d1",
            monologue_excerpts=["planner chose kill", "debate backed it"],
        )
        self.assertTrue(any(s.title == "Inner thought"
                             for s in e.sections))


class TestRendering(unittest.TestCase):
    def test_to_markdown_contains_summary_and_sections(self) -> None:
        e = ea.aggregate(
            decision_id="d1", verdict="scale",
            policies=[{"name": "p", "fit": 0.5, "score": 0.5}],
            evidence=[{"kind": "fact", "weight": 0.8, "note": "ROAS high"}],
        )
        md = e.to_markdown()
        self.assertIn("Why:", md)
        self.assertIn("Policies", md)
        self.assertIn("Evidence", md)

    def test_to_markdown_renders_no_data_placeholder(self) -> None:
        e = ea.aggregate(decision_id="d1")
        md = e.to_markdown()
        self.assertIn("no data", md)


class TestPolisher(unittest.TestCase):
    def test_polisher_rewrites_summary(self) -> None:
        e = ea.aggregate(
            decision_id="d1", verdict="kill",
            polisher=lambda s: f"POLISHED:{s[:20]}",
        )
        self.assertTrue(e.summary.startswith("POLISHED:"))

    def test_polisher_exception_swallowed(self) -> None:
        def broken(s):
            raise RuntimeError("nope")
        e = ea.aggregate(decision_id="d1", verdict="kill", polisher=broken)
        self.assertIn("kill", e.summary)


class TestDict(unittest.TestCase):
    def test_as_dict_complete(self) -> None:
        e = ea.aggregate(
            decision_id="d1", verdict="x",
            policies=[{"name": "p", "fit": 0.5, "score": 0.5}],
        )
        d = e.as_dict()
        self.assertEqual(d["decision_id"], "d1")
        self.assertIn("sections", d)


if __name__ == "__main__":
    unittest.main()
