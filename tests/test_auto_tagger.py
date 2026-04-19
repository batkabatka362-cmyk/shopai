"""Auto tagger tests."""
from __future__ import annotations

import unittest

from core.brain import auto_tagger as at


class TestMatcher(unittest.TestCase):
    def test_exact_match(self) -> None:
        self.assertTrue(at._matches("audio", "audio"))
        self.assertFalse(at._matches("audio", "fashion"))

    def test_list_match(self) -> None:
        self.assertTrue(at._matches(["a", "b"], "b"))
        self.assertFalse(at._matches(["a", "b"], "c"))

    def test_gt_lt(self) -> None:
        self.assertTrue(at._matches({"gt": 10, "lt": 20}, 15))
        self.assertFalse(at._matches({"gt": 10}, 5))

    def test_regex(self) -> None:
        self.assertTrue(
            at._matches({"regex": "wireless"}, "Wireless Speaker"),
        )

    def test_contains(self) -> None:
        self.assertTrue(
            at._matches({"contains": "audio"}, "AudioProduct"),
        )

    def test_non_numeric_fails_range(self) -> None:
        self.assertFalse(at._matches({"gt": 10}, "abc"))


class TestTagger(unittest.TestCase):
    def setUp(self) -> None:
        self.t = at.AutoTagger()

    def test_register_and_tag(self) -> None:
        self.t.register(at.Rule(
            name="premium",
            match={"price": {"gt": 80}},
            tags=("premium",),
        ))
        result = self.t.tag({"price": 99})
        self.assertIn("premium", result.tags)

    def test_empty_tags_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.register(at.Rule(name="r", match={}, tags=()))

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.register(at.Rule(name="", match={}, tags=("x",)))

    def test_rule_replaces_by_name(self) -> None:
        self.t.register(at.Rule(
            name="a", match={"x": 1}, tags=("v1",),
        ))
        self.t.register(at.Rule(
            name="a", match={"x": 1}, tags=("v2",),
        ))
        result = self.t.tag({"x": 1})
        self.assertIn("v2", result.tags)
        self.assertNotIn("v1", result.tags)

    def test_multiple_rules_union_tags(self) -> None:
        self.t.register_many([
            at.Rule(name="a", match={"price": {"gt": 80}},
                     tags=("premium",)),
            at.Rule(name="b", match={"niche": "audio"},
                     tags=("audio",)),
        ])
        result = self.t.tag({"price": 100, "niche": "audio"})
        self.assertIn("premium", result.tags)
        self.assertIn("audio", result.tags)

    def test_no_match_empty_tags(self) -> None:
        self.t.register(at.Rule(
            name="r", match={"price": {"gt": 1000}},
            tags=("expensive",),
        ))
        result = self.t.tag({"price": 10})
        self.assertEqual(result.tags, [])

    def test_missing_field_no_match(self) -> None:
        self.t.register(at.Rule(
            name="r", match={"missing_field": "x"},
            tags=("t",),
        ))
        self.assertEqual(self.t.tag({"other": 1}).tags, [])


class TestPriority(unittest.TestCase):
    def test_higher_priority_first_in_matched_list(self) -> None:
        t = at.AutoTagger()
        t.register(at.Rule(
            name="low", match={"x": 1}, tags=("a",), priority=0,
        ))
        t.register(at.Rule(
            name="high", match={"x": 1}, tags=("b",), priority=10,
        ))
        result = t.tag({"x": 1})
        self.assertEqual(result.matched_rules[0], "high")


class TestDeregister(unittest.TestCase):
    def test_deregister_removes(self) -> None:
        t = at.AutoTagger()
        t.register(at.Rule(name="r", match={"x": 1}, tags=("t",)))
        self.assertTrue(t.deregister("r"))
        self.assertFalse(t.deregister("r"))


class TestTrainFromExamples(unittest.TestCase):
    def test_learns_high_precision_rule(self) -> None:
        t = at.AutoTagger()
        examples = [
            {"features": {"niche": "audio"}, "tags": ["speaker"]},
            {"features": {"niche": "audio"}, "tags": ["speaker"]},
            {"features": {"niche": "audio"}, "tags": ["speaker"]},
            {"features": {"niche": "audio"}, "tags": ["speaker"]},
            {"features": {"niche": "audio"}, "tags": ["speaker"]},
            {"features": {"niche": "fashion"}, "tags": ["shirt"]},
        ]
        new_rules = t.train_from_examples(
            examples, min_support=3, min_precision=0.9,
        )
        self.assertTrue(
            any("audio" in r.name for r in new_rules),
        )
        # Verify the learned rule actually fires
        r = t.tag({"niche": "audio"})
        self.assertIn("speaker", r.tags)

    def test_empty_examples_no_new_rules(self) -> None:
        t = at.AutoTagger()
        self.assertEqual(t.train_from_examples([]), [])

    def test_low_support_no_rule(self) -> None:
        t = at.AutoTagger()
        examples = [
            {"features": {"x": "rare"}, "tags": ["t"]},
            {"features": {"x": "rare"}, "tags": ["t"]},
        ]
        rules = t.train_from_examples(
            examples, min_support=5, min_precision=0.9,
        )
        self.assertEqual(rules, [])


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        t = at.AutoTagger()
        t.register(at.Rule(name="a", match={}, tags=("x",)))
        t.register(at.Rule(name="b", match={}, tags=("y",)))
        s = t.stats()
        self.assertEqual(s["rule_count"], 2)


if __name__ == "__main__":
    unittest.main()
