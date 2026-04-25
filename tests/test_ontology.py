"""Ontology tests — entities, triples, subtypes, inference."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory import ontology as ont


class TestEntities(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.o = ont.Ontology(Path(self._tmp.name) / "o.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_upsert_and_types_of(self) -> None:
        self.o.upsert_entity("prod-1", "Product")
        self.assertIn("Product", self.o.types_of("prod-1"))

    def test_entity_can_have_multiple_types(self) -> None:
        self.o.upsert_entity("prod-1", "Product")
        self.o.upsert_entity("prod-1", "Launch")
        ts = self.o.types_of("prod-1")
        self.assertIn("Product", ts)
        self.assertIn("Launch", ts)


class TestTriples(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.o = ont.Ontology(Path(self._tmp.name) / "o.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_assert_triple_dedupes(self) -> None:
        self.assertTrue(self.o.assert_triple("a", "rel", "b"))
        self.assertFalse(self.o.assert_triple("a", "rel", "b"))

    def test_assert_auto_types_with_signature(self) -> None:
        self.o.declare_predicate(
            "supplied_by", "Product", "Supplier", functional=True,
        )
        self.o.assert_triple("sku-1", "supplied_by", "sup-1")
        self.assertIn("Product", self.o.types_of("sku-1"))
        self.assertIn("Supplier", self.o.types_of("sup-1"))

    def test_functional_predicate_replaces_prior_value(self) -> None:
        self.o.declare_predicate(
            "primary_niche", "Product", "Niche", functional=True,
        )
        self.o.assert_triple("p1", "primary_niche", "audio")
        self.o.assert_triple("p1", "primary_niche", "gardening")
        rows = self.o.query(subject="p1", predicate="primary_niche")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].object, "gardening")

    def test_retract_removes(self) -> None:
        self.o.assert_triple("a", "r", "b")
        self.assertTrue(self.o.retract_triple("a", "r", "b"))
        self.assertEqual(len(self.o.query(subject="a")), 0)

    def test_query_filters(self) -> None:
        self.o.assert_triple("a", "r1", "x")
        self.o.assert_triple("a", "r2", "y")
        self.o.assert_triple("b", "r1", "x")
        self.assertEqual(
            len(self.o.query(subject="a")), 2,
        )
        self.assertEqual(
            len(self.o.query(predicate="r1")), 2,
        )
        self.assertEqual(
            len(self.o.query(subject="a", predicate="r1")), 1,
        )


class TestSubtypes(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.o = ont.Ontology(Path(self._tmp.name) / "o.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_launch_is_a_product(self) -> None:
        self.o.declare_subtype("Launch", "Product")
        self.o.upsert_entity("launch-1", "Launch")
        self.assertTrue(self.o.is_a("launch-1", "Product"))
        self.assertTrue(self.o.is_a("launch-1", "Launch"))
        self.assertFalse(self.o.is_a("launch-1", "Supplier"))

    def test_transitive_subtypes(self) -> None:
        # Widget ⊑ Launch ⊑ Product
        self.o.declare_subtype("Launch", "Product")
        self.o.declare_subtype("Widget", "Launch")
        self.o.upsert_entity("w1", "Widget")
        self.assertTrue(self.o.is_a("w1", "Product"))

    def test_entities_of_type_includes_subtypes(self) -> None:
        self.o.declare_subtype("Launch", "Product")
        self.o.upsert_entity("prod-a", "Product")
        self.o.upsert_entity("launch-a", "Launch")
        products = self.o.entities_of_type("Product")
        ids = {e.id for e in products}
        self.assertIn("prod-a", ids)
        self.assertIn("launch-a", ids)

    def test_supertypes_transitive(self) -> None:
        self.o.declare_subtype("Widget", "Launch")
        self.o.declare_subtype("Launch", "Product")
        sups = self.o.supertypes_of("Widget")
        self.assertIn("Launch", sups)
        self.assertIn("Product", sups)


class TestSize(unittest.TestCase):
    def test_size_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        o = ont.Ontology(Path(tmp.name) / "o.db")
        o.declare_predicate("rel", "A", "B")
        o.declare_subtype("A", "B")
        o.assert_triple("x", "rel", "y")
        sz = o.size()
        self.assertGreater(sz["entities"], 0)
        self.assertGreater(sz["triples"], 0)
        self.assertEqual(sz["predicates"], 1)
        self.assertEqual(sz["subtype_edges"], 1)
        tmp.cleanup()


class TestBulkAssert(unittest.TestCase):
    def test_bulk_assert_counts_new(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        o = ont.Ontology(Path(tmp.name) / "o.db")
        n = o.bulk_assert([
            ("a", "r", "b"),
            ("a", "r", "c"),
            ("a", "r", "b"),   # dup
        ], source="seed")
        self.assertEqual(n, 2)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
