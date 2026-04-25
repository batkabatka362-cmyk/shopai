"""Context compactor tests."""
from __future__ import annotations

import unittest

from core.brain import context_compactor as cc


class TestConfig(unittest.TestCase):
    def test_bad_max_bytes_raises(self) -> None:
        with self.assertRaises(ValueError):
            cc.compact({}, max_bytes=10)

    def test_bad_max_list_items_raises(self) -> None:
        with self.assertRaises(ValueError):
            cc.compact({}, max_list_items=0)


class TestPrimitives(unittest.TestCase):
    def test_small_context_pass_through(self) -> None:
        brief = cc.compact({"x": 1, "y": "hello"})
        self.assertEqual(brief.fields, {"x": 1, "y": "hello"})
        self.assertFalse(brief.truncated)

    def test_string_truncation(self) -> None:
        brief = cc.compact({"long": "a" * 500})
        self.assertTrue(brief.fields["long"].endswith("..."))
        self.assertLessEqual(len(brief.fields["long"]), 200)

    def test_none_preserved(self) -> None:
        brief = cc.compact({"empty": None})
        self.assertIsNone(brief.fields["empty"])


class TestContainers(unittest.TestCase):
    def test_list_summary(self) -> None:
        brief = cc.compact({"xs": list(range(100))})
        self.assertIn("__list__", brief.fields["xs"])
        self.assertEqual(brief.fields["xs"]["count"], 100)
        self.assertEqual(len(brief.fields["xs"]["head"]), 5)

    def test_dict_summary_caps_keys(self) -> None:
        raw = {f"k{i}": i for i in range(20)}
        brief = cc.compact({"m": raw})
        self.assertLessEqual(len(brief.fields["m"]), 5)

    def test_tuple_handled_as_list(self) -> None:
        brief = cc.compact({"t": (1, 2, 3, 4)})
        self.assertIn("__list__", brief.fields["t"])


class TestBudget(unittest.TestCase):
    def test_budget_enforced(self) -> None:
        raw = {
            f"field_{i}": "x" * 200
            for i in range(20)
        }
        brief = cc.compact(raw, max_bytes=512)
        self.assertLessEqual(brief.byte_size, 512)
        self.assertTrue(brief.truncated)
        self.assertGreater(len(brief.dropped_fields), 0)

    def test_smallest_fields_kept_first(self) -> None:
        # Use lists / dicts that retain real bulk after summarisation
        # (strings get per-value truncation to 200 chars).
        raw = {
            "big_list": [{"x": "y" * 30} for _ in range(5)],
            "medium_list": [{"a": 1} for _ in range(5)],
            "tiny": 1,
        }
        brief = cc.compact(raw, max_bytes=256)
        self.assertIn("tiny", brief.fields)
        self.assertNotIn("big_list", brief.fields)


class TestPriorityFields(unittest.TestCase):
    def test_priority_always_kept(self) -> None:
        raw = {
            "bulk": "x" * 3000,
            "goal": "launch audio product",
        }
        brief = cc.compact(
            raw,
            priority_fields=("goal",),
            max_bytes=512,
        )
        self.assertIn("goal", brief.fields)

    def test_missing_priority_silently_skipped(self) -> None:
        brief = cc.compact(
            {"x": 1},
            priority_fields=("never_existed",),
        )
        self.assertEqual(brief.fields, {"x": 1})


class TestAsText(unittest.TestCase):
    def test_text_is_sorted_key_value(self) -> None:
        brief = cc.compact({"b": 2, "a": 1})
        text = brief.as_text()
        # Sorted → a comes before b
        self.assertLess(
            text.index("a:"), text.index("b:"),
        )

    def test_truncation_note_in_text(self) -> None:
        raw = {f"f{i}": "x" * 300 for i in range(10)}
        brief = cc.compact(raw, max_bytes=300)
        text = brief.as_text()
        self.assertIn("truncated", text)


class TestEmpty(unittest.TestCase):
    def test_empty_context_empty_brief(self) -> None:
        brief = cc.compact({})
        self.assertEqual(brief.fields, {})
        self.assertFalse(brief.truncated)


class TestDict(unittest.TestCase):
    def test_brief_serialises(self) -> None:
        brief = cc.compact({"x": 1})
        d = brief.as_dict()
        self.assertIn("fields", d)
        self.assertIn("budget", d)

    def test_none_context_handled(self) -> None:
        brief = cc.compact(None)  # type: ignore[arg-type]
        self.assertEqual(brief.fields, {})


if __name__ == "__main__":
    unittest.main()
