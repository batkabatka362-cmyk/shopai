"""Knowledge base — fact triple CRUD + supersession tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory import knowledge_base as kb


class TestAssertRecall(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.kb = kb.KnowledgeBase(Path(self._tmp.name) / "kb.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_assert_and_recall_scalar(self) -> None:
        self.kb.assert_fact("shopify", "max_mb", 5, source="docs")
        fact = self.kb.recall("shopify", "max_mb")
        self.assertEqual(fact.object, 5)
        self.assertEqual(fact.source, "docs")

    def test_supersession_returns_latest(self) -> None:
        self.kb.assert_fact("roas", "threshold", 1.5)
        self.kb.assert_fact("roas", "threshold", 1.8)
        fact = self.kb.recall("roas", "threshold")
        self.assertEqual(fact.object, 1.8)

    def test_history_returns_both_versions(self) -> None:
        self.kb.assert_fact("x", "y", 1)
        self.kb.assert_fact("x", "y", 2)
        hist = self.kb.history("x", "y")
        self.assertEqual([f.object for f in hist], [1, 2])

    def test_recall_unknown_returns_none(self) -> None:
        self.assertIsNone(self.kb.recall("none", "such"))

    def test_recall_subject_returns_all_live(self) -> None:
        self.kb.assert_fact("shopify", "a", 1)
        self.kb.assert_fact("shopify", "b", 2)
        facts = self.kb.recall("shopify")
        self.assertEqual(len(facts), 2)
        self.assertEqual({f.predicate for f in facts}, {"a", "b"})

    def test_list_subjects(self) -> None:
        self.kb.assert_fact("meta_ads", "min_budget", 1)
        self.kb.assert_fact("shopify", "max_mb", 5)
        self.assertEqual(self.kb.list_subjects(), ["meta_ads", "shopify"])

    def test_json_object(self) -> None:
        self.kb.assert_fact("adapter", "capabilities",
                            ["chat", "embed", "vision"])
        fact = self.kb.recall("adapter", "capabilities")
        self.assertEqual(fact.object, ["chat", "embed", "vision"])

    def test_rejects_empty_keys(self) -> None:
        with self.assertRaises(ValueError):
            self.kb.assert_fact("", "p", 1)
        with self.assertRaises(ValueError):
            self.kb.assert_fact("s", "", 1)


class TestSeedDefaults(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.kb = kb.KnowledgeBase(Path(self._tmp.name) / "kb.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_seed_writes_all_and_second_call_is_noop(self) -> None:
        first = kb.seed_defaults(self.kb)
        self.assertGreater(first, 0)
        second = kb.seed_defaults(self.kb)
        self.assertEqual(second, 0)

    def test_seed_facts_recallable(self) -> None:
        kb.seed_defaults(self.kb)
        self.assertEqual(
            self.kb.recall("shopify", "rate_limit_calls_per_second").object,
            2,
        )
        self.assertEqual(
            self.kb.recall("gemini", "embedding_dim").object,
            3072,
        )


if __name__ == "__main__":
    unittest.main()
