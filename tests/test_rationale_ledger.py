"""Tests for core.decision.rationale_ledger — Track 4."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.decision.rationale_ledger import (
    PersistentRationaleLedger,
    RationaleRecord,
    _count_nodes,
    _serialise_node,
    get_rationale_ledger,
    reset_rationale_ledger_for_tests,
)


def _node(
    id_="root", label="Launch decision",
    detail="Activate camp_abc", weight=0.0,
    children=None,
):
    n = MagicMock()
    n.id = id_
    n.label = label
    n.detail = detail
    n.weight = weight
    n.children = children or []
    n.ts = 100.0
    return n


def _rationale(
    decision_id="dec_1", summary="test",
    root=None,
):
    r = MagicMock()
    r.decision_id = decision_id
    r.summary = summary
    r.ts = 100.0
    r.root = root or _node()
    return r


def _build(tmp, **kw):
    defaults = dict(
        db_path=Path(tmp) / "r.db",
    )
    defaults.update(kw)
    return PersistentRationaleLedger(**defaults)


class TestNodeHelpers(unittest.TestCase):
    def test_serialise_empty_node(self):
        out = _serialise_node(
            {"id": "x", "label": "y"},
            budget=[100],
        )
        self.assertEqual(out["id"], "x")
        self.assertEqual(out["label"], "y")
        self.assertEqual(out["children"], [])

    def test_serialise_budget_truncates(self):
        # 5 nested children, budget 2 → first 2 then truncate
        deep = {
            "id": "1", "label": "a",
            "children": [{
                "id": "2", "label": "b",
                "children": [{
                    "id": "3", "label": "c",
                }],
            }],
        }
        out = _serialise_node(deep, budget=[2])
        self.assertEqual(out["label"], "a")
        self.assertEqual(len(out["children"]), 1)

    def test_count_nodes(self):
        tree = {
            "id": "r", "children": [
                {"id": "a", "children": []},
                {"id": "b", "children": [
                    {"id": "c", "children": []},
                ]},
            ],
        }
        self.assertEqual(_count_nodes(tree), 4)


class TestRecord(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = _build(self._tmp.name)

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def test_record_missing_decision_id(self):
        with self.assertRaises(ValueError):
            self.ledger.record(
                _rationale(decision_id=""),
            )

    def test_record_none_raises(self):
        with self.assertRaises(ValueError):
            self.ledger.record(None)

    def test_record_roundtrip(self):
        rec = self.ledger.record(_rationale())
        got = self.ledger.get("dec_1")
        self.assertEqual(got.decision_id, "dec_1")
        self.assertEqual(got.summary, "test")

    def test_record_accepts_dict(self):
        rec = self.ledger.record({
            "decision_id": "dict_dec",
            "summary": "from dict",
            "root": {
                "id": "r", "label": "lbl", "detail": "d",
                "children": [],
            },
        })
        self.assertEqual(rec.decision_id, "dict_dec")
        got = self.ledger.get("dict_dec")
        self.assertEqual(got.tree["label"], "lbl")

    def test_record_overwrites_on_second_call(self):
        self.ledger.record(_rationale(
            decision_id="x", summary="first",
        ))
        self.ledger.record(_rationale(
            decision_id="x", summary="second",
        ))
        got = self.ledger.get("x")
        self.assertEqual(got.summary, "second")

    def test_node_count_populated(self):
        root = _node(
            id_="r",
            children=[
                _node(id_="c1"), _node(id_="c2"),
            ],
        )
        rec = self.ledger.record(
            _rationale(root=root),
        )
        self.assertEqual(rec.node_count, 3)


class TestQuery(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = _build(self._tmp.name)

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.ledger.get("nope"))

    def test_recent_newest_first(self):
        for i in range(3):
            r = _rationale(decision_id=f"d{i}")
            r.ts = 100.0 + i * 10
            self.ledger.record(r)
        recent = self.ledger.recent()
        self.assertEqual(recent[0].decision_id, "d2")
        self.assertEqual(recent[-1].decision_id, "d0")

    def test_explain_missing_id(self):
        out = self.ledger.explain("nope")
        self.assertIn("No rationale found", out)

    def test_explain_renders_tree(self):
        root = _node(
            label="Activate",
            detail="budget OK",
            children=[
                _node(
                    label="Risk OK",
                    detail="within cap",
                    weight=0.5,
                ),
            ],
        )
        self.ledger.record(
            _rationale(
                decision_id="dx", summary="summary",
                root=root,
            ),
        )
        text = self.ledger.explain("dx")
        self.assertIn("Decision: dx", text)
        self.assertIn("Activate", text)
        self.assertIn("Risk OK", text)

    def test_stats_shape(self):
        self.ledger.record(_rationale())
        s = self.ledger.stats()
        self.assertEqual(s["total_rationales"], 1)


class TestSingleton(unittest.TestCase):
    def test_reuse(self):
        reset_rationale_ledger_for_tests()
        try:
            a = get_rationale_ledger()
            b = get_rationale_ledger()
            self.assertIs(a, b)
        finally:
            reset_rationale_ledger_for_tests()


class TestDict(unittest.TestCase):
    def test_record_dict(self):
        r = RationaleRecord(
            decision_id="x", summary="y",
        )
        self.assertEqual(r.as_dict()["decision_id"], "x")


if __name__ == "__main__":
    unittest.main()
