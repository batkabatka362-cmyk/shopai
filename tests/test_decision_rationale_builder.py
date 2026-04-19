"""Decision rationale builder tests."""
from __future__ import annotations

import unittest

from core.brain import decision_rationale_builder as drb


class TestStart(unittest.TestCase):
    def setUp(self) -> None:
        self.b = drb.DecisionRationaleBuilder()

    def test_blank_decision_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.start(decision_id="", summary="x")

    def test_blank_summary_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.start(decision_id="d", summary="")

    def test_start_creates_root(self) -> None:
        r = self.b.start(
            decision_id="d1",
            summary="launch the ad",
        )
        self.assertEqual(r.decision_id, "d1")
        self.assertEqual(r.root.headline, "launch the ad")

    def test_double_start_raises(self) -> None:
        self.b.start(decision_id="d", summary="x")
        with self.assertRaises(ValueError):
            self.b.start(decision_id="d", summary="y")


class TestAdd(unittest.TestCase):
    def setUp(self) -> None:
        self.b = drb.DecisionRationaleBuilder()
        self.r = self.b.start(
            decision_id="d1", summary="launch ad",
        )

    def test_unknown_decision_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.add(
                "nope", kind="rule",
                headline="x",
            )

    def test_blank_headline_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.add(
                "d1", kind="rule", headline="",
            )

    def test_bad_weight_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.add(
                "d1", kind="rule",
                headline="x", weight=2.0,
            )

    def test_add_appends(self) -> None:
        node = self.b.add(
            "d1", kind="rule",
            headline="roas below 1.5",
            weight=0.8,
            references=("rule_12",),
        )
        self.assertEqual(node.kind, "rule")
        self.assertEqual(
            self.r.root.children[0].id, node.id,
        )

    def test_nested(self) -> None:
        parent = self.b.add(
            "d1", kind="rule",
            headline="p", weight=0.6,
        )
        child = self.b.add(
            "d1", kind="evidence",
            headline="e", weight=0.4,
            parent_id=parent.id,
        )
        self.assertEqual(parent.children[0].id, child.id)

    def test_unknown_parent_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.add(
                "d1", kind="rule",
                headline="x", parent_id="ghost",
            )


class TestCommit(unittest.TestCase):
    def test_commit_moves_to_archive(self) -> None:
        b = drb.DecisionRationaleBuilder()
        b.start(decision_id="d", summary="s")
        r = b.commit("d")
        self.assertEqual(r.decision_id, "d")
        self.assertEqual(b.stats()["archived"], 1)
        self.assertEqual(b.stats()["in_progress"], 0)

    def test_commit_unknown_raises(self) -> None:
        b = drb.DecisionRationaleBuilder()
        with self.assertRaises(ValueError):
            b.commit("nope")

    def test_abandon(self) -> None:
        b = drb.DecisionRationaleBuilder()
        b.start(decision_id="d", summary="s")
        self.assertTrue(b.abandon("d"))
        self.assertEqual(b.stats()["in_progress"], 0)

    def test_abandon_unknown(self) -> None:
        b = drb.DecisionRationaleBuilder()
        self.assertFalse(b.abandon("nope"))


class TestMarkdown(unittest.TestCase):
    def test_markdown_includes_nesting(self) -> None:
        b = drb.DecisionRationaleBuilder()
        b.start(decision_id="d", summary="launch")
        parent = b.add(
            "d", kind="rule", headline="rule A",
            weight=0.5,
        )
        b.add(
            "d", kind="evidence",
            headline="cited X", weight=0.3,
            parent_id=parent.id,
        )
        r = b.commit("d")
        md = r.as_markdown()
        self.assertIn("rule A", md)
        self.assertIn("cited X", md)
        self.assertIn("  -", md)   # nested bullet


class TestQueries(unittest.TestCase):
    def test_get(self) -> None:
        b = drb.DecisionRationaleBuilder()
        b.start(decision_id="d", summary="x")
        # Active-only
        self.assertIsNotNone(b.get("d"))
        b.commit("d")
        # Archive
        self.assertIsNotNone(b.get("d"))

    def test_recent(self) -> None:
        b = drb.DecisionRationaleBuilder()
        for i in range(3):
            b.start(decision_id=f"d{i}", summary="s")
            b.commit(f"d{i}")
        r = b.recent(limit=2)
        self.assertEqual(len(r), 2)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        b = drb.DecisionRationaleBuilder()
        b.start(decision_id="d", summary="s")
        s = b.stats()
        self.assertEqual(s["in_progress"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        b = drb.DecisionRationaleBuilder()
        b.start(decision_id="d", summary="s")
        b.commit("d")
        self.assertEqual(b.reset(), 1)


class TestDict(unittest.TestCase):
    def test_node_serialises(self) -> None:
        b = drb.DecisionRationaleBuilder()
        r = b.start(decision_id="d", summary="s")
        d = r.root.as_dict()
        self.assertIn("headline", d)

    def test_rationale_serialises(self) -> None:
        b = drb.DecisionRationaleBuilder()
        r = b.start(decision_id="d", summary="s")
        d = r.as_dict()
        self.assertIn("root", d)


if __name__ == "__main__":
    unittest.main()
