"""Knowledge graph tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory import knowledge_graph as kg


class TestSetup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.g = kg.KnowledgeGraph(Path(self._tmp.name) / "kg.db")

    def tearDown(self) -> None:
        self.g.close()
        self._tmp.cleanup()


class TestAssert(TestSetup):
    def test_assert_and_get(self) -> None:
        self.g.assert_triple("p1", "name", "Blue Widget", is_literal=True)
        triples = self.g.get("p1", "name")
        self.assertEqual(len(triples), 1)
        self.assertEqual(triples[0].object, "Blue Widget")

    def test_blank_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.g.assert_triple("", "p", "o")

    def test_dup_replaces(self) -> None:
        self.g.assert_triple("p1", "name", "A", confidence=0.5)
        self.g.assert_triple("p1", "name", "A", confidence=0.9)
        # Unique constraint overwrites — still 1 triple but higher conf
        triples = self.g.get("p1", "name")
        self.assertEqual(len(triples), 1)
        self.assertAlmostEqual(triples[0].confidence, 0.9)


class TestRetract(TestSetup):
    def test_retract_by_full_triple(self) -> None:
        self.g.assert_triple("p", "a", "b")
        n = self.g.retract(subject="p", predicate="a", obj="b")
        self.assertEqual(n, 1)
        self.assertEqual(self.g.get("p", "a"), [])

    def test_retract_by_subject(self) -> None:
        self.g.assert_triple("p", "a", "1")
        self.g.assert_triple("p", "b", "2")
        n = self.g.retract(subject="p")
        self.assertEqual(n, 2)

    def test_retract_no_clause_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.g.retract()


class TestPredecessors(TestSetup):
    def test_predecessors(self) -> None:
        self.g.assert_triple("p1", "has_category", "audio")
        self.g.assert_triple("p2", "has_category", "audio")
        self.g.assert_triple("p3", "has_category", "fashion")
        audio = self.g.predecessors("audio", "has_category")
        self.assertEqual({t.subject for t in audio}, {"p1", "p2"})


class TestClassHierarchy(TestSetup):
    def test_direct_is_a(self) -> None:
        self.g.assert_triple("p1", kg.RDF_TYPE, "Product")
        self.assertTrue(self.g.is_a("p1", "Product"))

    def test_transitive_subclass(self) -> None:
        self.g.assert_triple("p1", kg.RDF_TYPE, "Headphones")
        self.g.assert_triple("Headphones", kg.RDFS_SUBCLASS, "Audio")
        self.g.assert_triple("Audio", kg.RDFS_SUBCLASS, "Electronics")
        self.g.assert_triple("Electronics", kg.RDFS_SUBCLASS, "Product")
        self.assertTrue(self.g.is_a("p1", "Audio"))
        self.assertTrue(self.g.is_a("p1", "Electronics"))
        self.assertTrue(self.g.is_a("p1", "Product"))

    def test_not_in_hierarchy_false(self) -> None:
        self.g.assert_triple("p1", kg.RDF_TYPE, "Audio")
        self.assertFalse(self.g.is_a("p1", "Apparel"))

    def test_instances_of_transitive(self) -> None:
        self.g.assert_triple("p1", kg.RDF_TYPE, "Headphones")
        self.g.assert_triple("p2", kg.RDF_TYPE, "Speakers")
        self.g.assert_triple("Headphones", kg.RDFS_SUBCLASS, "Audio")
        self.g.assert_triple("Speakers", kg.RDFS_SUBCLASS, "Audio")
        instances = self.g.instances_of("Audio")
        self.assertEqual(set(instances), {"p1", "p2"})

    def test_ancestors_of(self) -> None:
        self.g.assert_triple("Headphones", kg.RDFS_SUBCLASS, "Audio")
        self.g.assert_triple("Audio", kg.RDFS_SUBCLASS, "Electronics")
        ancestors = self.g.ancestors_of("Headphones")
        self.assertIn("Audio", ancestors)
        self.assertIn("Electronics", ancestors)


class TestInverse(TestSetup):
    def test_inverse_declaration(self) -> None:
        self.g.declare_inverse("has_part", "part_of")
        self.g.assert_triple("part_a", "part_of", "whole")
        # Query the other direction: whole has_part part_a
        triples = self.g.get("whole", "has_part")
        self.assertTrue(any(t.object == "part_a" for t in triples))

    def test_inverse_blank_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.g.declare_inverse("x", "")


class TestIngest(TestSetup):
    def test_ingest_many(self) -> None:
        triples = [
            kg.Triple(subject=f"p{i}", predicate="kind", object="widget")
            for i in range(5)
        ]
        n = self.g.ingest(triples)
        self.assertEqual(n, 5)
        self.assertEqual(self.g.stats()["triples"], 5)


class TestStats(TestSetup):
    def test_stats(self) -> None:
        self.g.assert_triple("a", "p", "1")
        self.g.assert_triple("b", "p", "2")
        self.g.assert_triple("a", "q", "3")
        s = self.g.stats()
        self.assertEqual(s["triples"], 3)
        self.assertEqual(s["distinct_subjects"], 2)
        self.assertEqual(s["distinct_predicates"], 2)


class TestDict(TestSetup):
    def test_triple_serialises(self) -> None:
        self.g.assert_triple("a", "p", "b", confidence=0.7, source="test")
        triples = self.g.get("a", "p")
        d = triples[0].as_dict()
        self.assertEqual(d["confidence"], 0.7)
        self.assertEqual(d["source"], "test")


class TestMaxDepth(TestSetup):
    def test_cycle_protected(self) -> None:
        # A deliberate subclass cycle should not infinite-loop.
        self.g.assert_triple("A", kg.RDFS_SUBCLASS, "B")
        self.g.assert_triple("B", kg.RDFS_SUBCLASS, "A")
        self.g.assert_triple("thing", kg.RDF_TYPE, "A")
        # Should terminate without recursion error.
        self.assertTrue(self.g.is_a("thing", "B"))


if __name__ == "__main__":
    unittest.main()
