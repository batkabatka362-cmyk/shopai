"""Invariant detector tests."""
from __future__ import annotations

import unittest

from core.brain import invariant_detector as inv


class TestEquality(unittest.TestCase):
    def test_constant_field_detected(self) -> None:
        rows = [{"currency": "USD", "n": i} for i in range(10)]
        found = inv.detect(rows)
        eq = [x for x in found if x.kind == "equality"
              and x.field == "currency"]
        self.assertEqual(len(eq), 1)
        self.assertEqual(eq[0].constant, "USD")

    def test_varying_field_no_equality(self) -> None:
        rows = [{"x": 1}, {"x": 2}, {"x": 3}]
        found = inv.detect(rows)
        eq = [x for x in found if x.kind == "equality" and x.field == "x"]
        self.assertEqual(eq, [])


class TestRange(unittest.TestCase):
    def test_numeric_range_detected(self) -> None:
        rows = [{"price": 5}, {"price": 20}, {"price": 15}]
        found = inv.detect(rows)
        rg = [x for x in found if x.kind == "range" and x.field == "price"]
        self.assertEqual(len(rg), 1)
        self.assertEqual(rg[0].lo, 5)
        self.assertEqual(rg[0].hi, 20)

    def test_same_value_skipped_for_range(self) -> None:
        rows = [{"x": 1}, {"x": 1}, {"x": 1}]
        found = inv.detect(rows)
        rg = [x for x in found if x.kind == "range"]
        self.assertEqual(rg, [])


class TestNonNull(unittest.TestCase):
    def test_always_present_detected(self) -> None:
        rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        found = inv.detect(rows)
        nn = [x for x in found if x.kind == "non_null"
              and x.field == "id"]
        self.assertEqual(len(nn), 1)

    def test_any_missing_blocks_non_null(self) -> None:
        rows = [{"id": "a"}, {}, {"id": "c"}]
        found = inv.detect(rows)
        nn = [x for x in found if x.kind == "non_null" and x.field == "id"]
        self.assertEqual(nn, [])


class TestImplication(unittest.TestCase):
    def test_niche_implies_tone(self) -> None:
        rows = [
            {"niche": "audio", "tone": "luxury"},
            {"niche": "audio", "tone": "luxury"},
            {"niche": "audio", "tone": "luxury"},
            {"niche": "fashion", "tone": "friendly"},
            {"niche": "fashion", "tone": "friendly"},
            {"niche": "fashion", "tone": "friendly"},
        ]
        found = inv.detect(
            rows, implication_pairs=[("niche", "tone")],
        )
        implications = [x for x in found if x.kind == "implication"]
        self.assertGreaterEqual(len(implications), 2)

    def test_small_sample_skipped(self) -> None:
        rows = [
            {"niche": "x", "tone": "y"},
            {"niche": "x", "tone": "y"},
        ]
        found = inv.detect(
            rows, implication_pairs=[("niche", "tone")],
        )
        implications = [x for x in found if x.kind == "implication"]
        self.assertEqual(implications, [])

    def test_too_many_targets_skipped(self) -> None:
        rows = [
            {"a": "g", "b": str(i)} for i in range(10)
        ]
        found = inv.detect(rows, implication_pairs=[("a", "b")])
        implications = [x for x in found if x.kind == "implication"]
        self.assertEqual(implications, [])


class TestCheck(unittest.TestCase):
    def test_equality_check_holds(self) -> None:
        i = inv.Invariant(kind="equality", field="x", constant=5)
        self.assertTrue(inv.check(i, {"x": 5}))
        self.assertFalse(inv.check(i, {"x": 6}))

    def test_range_check_holds(self) -> None:
        i = inv.Invariant(kind="range", field="p", lo=1.0, hi=10.0)
        self.assertTrue(inv.check(i, {"p": 5.5}))
        self.assertFalse(inv.check(i, {"p": 100}))

    def test_non_null_violated_on_missing(self) -> None:
        i = inv.Invariant(kind="non_null", field="x")
        self.assertFalse(inv.check(i, {}))
        self.assertTrue(inv.check(i, {"x": "ok"}))

    def test_implication_vacuously_true_when_premise_fails(self) -> None:
        i = inv.Invariant(
            kind="implication", field="tone",
            given_field="niche", given_value="audio",
            allowed_values=frozenset({"luxury"}),
        )
        self.assertTrue(inv.check(i, {"niche": "fashion", "tone": "xyz"}))
        self.assertTrue(inv.check(i, {"niche": "audio", "tone": "luxury"}))
        self.assertFalse(inv.check(i, {"niche": "audio", "tone": "clickbait"}))


class TestSweep(unittest.TestCase):
    def test_sweep_returns_violations(self) -> None:
        invs = [
            inv.Invariant(kind="non_null", field="id"),
            inv.Invariant(kind="range", field="p", lo=0.0, hi=10.0),
        ]
        violated = inv.sweep(invs, {"id": "", "p": 50})
        self.assertEqual(len(violated), 2)

    def test_sweep_empty_when_satisfied(self) -> None:
        invs = [inv.Invariant(kind="range", field="p", lo=0.0, hi=10.0)]
        self.assertEqual(inv.sweep(invs, {"p": 5}), [])


class TestDescribe(unittest.TestCase):
    def test_equality_describe(self) -> None:
        i = inv.Invariant(kind="equality", field="currency",
                           constant="USD", sample_size=10)
        self.assertIn("always", i.describe())
        self.assertIn("USD", i.describe())

    def test_range_describe(self) -> None:
        i = inv.Invariant(kind="range", field="p",
                           lo=1.0, hi=5.0, sample_size=10)
        self.assertIn("[1.0, 5.0]", i.describe())


class TestConfidence(unittest.TestCase):
    def test_more_samples_higher_confidence(self) -> None:
        small = inv.Invariant(kind="equality", field="x",
                               constant=1, sample_size=4)
        large = inv.Invariant(kind="equality", field="x",
                               constant=1, sample_size=400)
        self.assertLess(small.confidence, large.confidence)


if __name__ == "__main__":
    unittest.main()
