"""Answer synthesizer tests."""
from __future__ import annotations

import unittest

from core.brain import answer_synthesizer as an


class TestBundle(unittest.TestCase):
    def test_add_fact(self) -> None:
        b = an.Bundle()
        b.add("policy", "audio_kill matches this context", 0.8)
        self.assertEqual(len(b.facts), 1)

    def test_empty_text_skipped(self) -> None:
        b = an.Bundle()
        b.add("policy", "", 0.8)
        self.assertEqual(b.facts, [])

    def test_weight_clamped(self) -> None:
        b = an.Bundle()
        b.add("r", "text", weight=5.0)
        self.assertEqual(b.facts[0].weight, 1.0)

    def test_caveat(self) -> None:
        b = an.Bundle()
        b.caveat("margin floor close")
        self.assertEqual(len(b.caveats), 1)


class TestSynthesize(unittest.TestCase):
    def test_strong_support_high_confidence(self) -> None:
        b = an.Bundle()
        b.add("policy", "audio_kill", 0.9)
        b.add("reward", "niche=audio positive", 0.8)
        b.add("search", "relevant memory row", 0.7)
        ans = an.synthesize("should I kill?", b)
        self.assertGreater(ans.confidence, 0.7)
        self.assertEqual(len(ans.supporting_points), 3)

    def test_no_evidence_zero_confidence(self) -> None:
        ans = an.synthesize("vague?", an.Bundle())
        self.assertEqual(ans.confidence, 0.0)
        self.assertIn("No strong evidence", ans.summary)

    def test_caveats_dragged_confidence(self) -> None:
        b = an.Bundle()
        b.add("policy", "x", 0.9)
        b.caveat("one caveat")
        b.caveat("second caveat")
        b.caveat("third caveat")
        ans = an.synthesize("should I?", b)
        # Base ≈ 0.9, caveat penalty up to 0.3 → confidence 0.6ish
        self.assertLess(ans.confidence, 0.9)

    def test_top_facts_limited(self) -> None:
        b = an.Bundle()
        for i in range(10):
            b.add("r", f"fact {i}", 0.5)
        ans = an.synthesize("x?", b, top_facts=3)
        self.assertEqual(len(ans.supporting_points), 3)

    def test_top_facts_sorted_by_weight(self) -> None:
        b = an.Bundle()
        b.add("a", "low", 0.2)
        b.add("b", "high", 0.9)
        b.add("c", "mid", 0.5)
        ans = an.synthesize("q", b, top_facts=3)
        weights = [f.weight for f in ans.supporting_points]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_empty_question(self) -> None:
        ans = an.synthesize("", an.Bundle())
        self.assertEqual(ans.summary, "empty question")
        self.assertEqual(ans.confidence, 0.0)


class TestFollowUps(unittest.TestCase):
    def test_no_evidence_suggests_gathering(self) -> None:
        ans = an.synthesize("x?", an.Bundle())
        self.assertTrue(any(
            "Gather" in s for s in ans.suggested_follow_ups
        ))

    def test_missing_policy_source_suggested(self) -> None:
        b = an.Bundle()
        b.add("search", "some match", 0.5)
        ans = an.synthesize("x?", b)
        self.assertTrue(any(
            "policy" in s for s in ans.suggested_follow_ups
        ))

    def test_missing_reward_source_suggested(self) -> None:
        b = an.Bundle()
        b.add("policy", "p", 0.5)
        ans = an.synthesize("x?", b)
        self.assertTrue(any(
            "reward" in s for s in ans.suggested_follow_ups
        ))

    def test_caveats_addressed_suggestion(self) -> None:
        b = an.Bundle()
        b.add("policy", "p", 0.5)
        b.add("reward", "r", 0.5)
        b.caveat("risky")
        ans = an.synthesize("x?", b)
        self.assertTrue(any(
            "caveats" in s for s in ans.suggested_follow_ups
        ))


class TestPolisher(unittest.TestCase):
    def test_polisher_applied(self) -> None:
        b = an.Bundle()
        b.add("p", "fact", 0.8)
        ans = an.synthesize(
            "q?", b,
            polisher=lambda s: f"POLISHED:{s[:30]}",
        )
        self.assertTrue(ans.summary.startswith("POLISHED:"))

    def test_polisher_exception_swallowed(self) -> None:
        b = an.Bundle()
        b.add("p", "fact", 0.8)
        def broken(s):
            raise RuntimeError("no")
        ans = an.synthesize("q?", b, polisher=broken)
        self.assertIn("q?", ans.summary)


class TestAsDict(unittest.TestCase):
    def test_answer_dict(self) -> None:
        b = an.Bundle()
        b.add("p", "f", 0.9)
        ans = an.synthesize("q?", b)
        d = ans.as_dict()
        for key in ("question", "summary", "confidence",
                     "supporting_points", "caveats",
                     "suggested_follow_ups"):
            self.assertIn(key, d)


class TestBundleBuilder(unittest.TestCase):
    def test_builder_returns_empty_bundle(self) -> None:
        b = an.bundle_builder()
        self.assertEqual(b.facts, [])
        self.assertEqual(b.caveats, [])


if __name__ == "__main__":
    unittest.main()
