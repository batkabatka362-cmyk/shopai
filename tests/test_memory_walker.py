"""Memory walker tests — neighbors / walk / find / answer."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory import memory_walker as mw
from core.memory.ontology import Ontology


def _make_ontology(tmp_dir: str) -> "Ontology":
    o = Ontology(Path(tmp_dir) / "o.db")
    # Schema
    o.declare_predicate("supplied_by", "Product", "Supplier",
                        functional=True)
    o.declare_predicate("in_niche", "Product", "Niche",
                        functional=True)
    o.declare_subtype("Launch", "Product")
    # Entities + triples
    o.upsert_entity("sup-china", "Supplier")
    o.upsert_entity("sup-us", "Supplier")
    o.upsert_entity("audio", "Niche")
    o.upsert_entity("fashion", "Niche")
    o.assert_triple("L1", "in_niche", "audio")
    o.assert_triple("L1", "supplied_by", "sup-china")
    o.assert_triple("L2", "in_niche", "audio")
    o.assert_triple("L2", "supplied_by", "sup-us")
    o.assert_triple("L3", "in_niche", "fashion")
    o.assert_triple("L3", "supplied_by", "sup-china")
    # Mark L1..L3 as Launches (predicate auto-typed them as Product)
    o.upsert_entity("L1", "Launch")
    o.upsert_entity("L2", "Launch")
    o.upsert_entity("L3", "Launch")
    return o


class TestNeighbors(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ont = _make_ontology(self._tmp.name)
        self.w = mw.MemoryWalker(ont=self.ont)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_out_neighbors_returns_supplier(self) -> None:
        n = self.w.neighbors("L1", predicate="supplied_by",
                              direction="out")
        self.assertEqual(n, ["sup-china"])

    def test_in_neighbors_returns_products(self) -> None:
        n = self.w.neighbors("sup-china", predicate="supplied_by",
                              direction="in")
        self.assertIn("L1", n)
        self.assertIn("L3", n)

    def test_unknown_entity_empty(self) -> None:
        n = self.w.neighbors("nobody", direction="out")
        self.assertEqual(n, [])


class TestWalk(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ont = _make_ontology(self._tmp.name)
        self.w = mw.MemoryWalker(ont=self.ont)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_two_hop_niche_peers(self) -> None:
        # Start at L1 → niche → back to products in that niche
        result = self.w.walk(
            "L1", [("in_niche", "out"), ("in_niche", "in")],
        )
        self.assertIn("L2", result.reached)
        # L1 is already in visited set, so not in the new frontier
        self.assertNotIn("L1", result.reached)

    def test_max_depth_respected(self) -> None:
        w = mw.MemoryWalker(ont=self.ont, max_depth=1)
        result = w.walk(
            "L1",
            [("in_niche", "out"),
             ("in_niche", "in"),
             ("supplied_by", "out")],
        )
        # Only one hop actually taken
        self.assertEqual(len(result.pattern), 1)


class TestFind(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ont = _make_ontology(self._tmp.name)
        self.w = mw.MemoryWalker(ont=self.ont)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_products_supplied_by_china(self) -> None:
        # Start at Suppliers, walk "supplied_by" inbound → Products
        targets = self.w.find(
            start_type="Supplier",
            pattern=[("supplied_by", "in")],
            target_type="Product",
        )
        # Should find L1 + L3 (Launch ⊑ Product)
        self.assertIn("L1", targets)
        self.assertIn("L3", targets)


class TestAnswer(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ont = _make_ontology(self._tmp.name)
        self.w = mw.MemoryWalker(ont=self.ont)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_supplied_by_pattern(self) -> None:
        out = self.w.answer("which products supplied by sup-china")
        self.assertEqual(out["matched_pattern"], "supplied_by")
        self.assertIn("L1", out["answer_ids"])
        self.assertIn("L3", out["answer_ids"])

    def test_list_type_pattern(self) -> None:
        out = self.w.answer("list launches")
        self.assertEqual(out["matched_pattern"], "list_type")
        self.assertEqual(set(out["answer_ids"]), {"L1", "L2", "L3"})

    def test_unrecognised_returns_error(self) -> None:
        out = self.w.answer("what's the weather?")
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
