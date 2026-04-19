"""Knowledge validator tests."""
from __future__ import annotations

import unittest

from core.memory import knowledge_validator as kv


class TestDirect(unittest.TestCase):
    def test_agreement_no_conflict(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            kv.Claim("p1", "name", "Blue Widget", "shopify", 0.9),
            kv.Claim("p1", "name", "Blue Widget", "autods", 0.7),
        ])
        self.assertEqual(report.conflicts, [])

    def test_direct_conflict_flagged(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            kv.Claim("p1", "name", "Blue Widget", "shopify", 0.9),
            kv.Claim("p1", "name", "Red Widget", "autods", 0.6),
        ])
        self.assertEqual(len(report.conflicts), 1)
        self.assertEqual(report.conflicts[0].kind, "direct")

    def test_severity_high_on_confident_claim(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            kv.Claim("p1", "price", 20, "a", 0.95),
            kv.Claim("p1", "price", 30, "b", 0.85),
        ])
        self.assertEqual(report.conflicts[0].severity, "high")

    def test_resolution_highest_confidence_when_clear_gap(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            kv.Claim("p1", "price", 20, "a", 0.95),
            kv.Claim("p1", "price", 30, "b", 0.4),
        ])
        self.assertEqual(
            report.conflicts[0].resolution, "highest_confidence",
        )

    def test_resolution_owner_review_when_close(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            kv.Claim("p1", "price", 20, "a", 0.7),
            kv.Claim("p1", "price", 30, "b", 0.65),
        ])
        self.assertEqual(
            report.conflicts[0].resolution, "owner_review",
        )

    def test_functional_predicate_filter(self) -> None:
        # Restricting to a functional set means predicates outside
        # the set are NOT flagged even when objects differ.
        v = kv.KnowledgeValidator(
            functional_predicates={"price"},
        )
        report = v.validate([
            kv.Claim("p1", "tag", "vip", "a"),
            kv.Claim("p1", "tag", "new", "b"),
        ])
        self.assertEqual(report.conflicts, [])


class TestTypeConflict(unittest.TestCase):
    def test_product_and_supplier_flagged(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            kv.Claim("e1", "type", "Product", "ontology"),
            kv.Claim("e1", "type", "Supplier", "kb"),
        ])
        # Direct conflict on predicate 'type' with different objects
        # fires — plus the type_conflict rule also catches the
        # incompatible-class pair.
        kinds = [c.kind for c in report.conflicts]
        self.assertIn("type_conflict", kinds)

    def test_compatible_types_not_flagged(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            kv.Claim("e1", "type", "Product", "a"),
            kv.Claim("e1", "type", "Launch", "b"),
        ])
        type_conflicts = [c for c in report.conflicts
                           if c.kind == "type_conflict"]
        self.assertEqual(type_conflicts, [])


class TestRange(unittest.TestCase):
    def test_out_of_range_flagged(self) -> None:
        v = kv.KnowledgeValidator()
        v.register_range("margin_pct", 0.0, 1.0)
        report = v.validate([
            kv.Claim("p1", "margin_pct", 1.5, "a"),
        ])
        self.assertEqual(report.conflicts[0].kind, "range")

    def test_within_range_ok(self) -> None:
        v = kv.KnowledgeValidator()
        v.register_range("margin_pct", 0.0, 1.0)
        report = v.validate([
            kv.Claim("p1", "margin_pct", 0.4, "a"),
        ])
        range_conflicts = [c for c in report.conflicts
                            if c.kind == "range"]
        self.assertEqual(range_conflicts, [])

    def test_non_numeric_ignored(self) -> None:
        v = kv.KnowledgeValidator()
        v.register_range("x", 0, 10)
        report = v.validate([
            kv.Claim("a", "x", "not_a_number", "s"),
        ])
        range_conflicts = [c for c in report.conflicts
                            if c.kind == "range"]
        self.assertEqual(range_conflicts, [])


class TestCoerce(unittest.TestCase):
    def test_dict_claim_accepted(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            {"subject": "p1", "predicate": "name",
             "object": "a", "source": "s", "confidence": 0.9},
            {"subject": "p1", "predicate": "name",
             "object": "b", "source": "t", "confidence": 0.5},
        ])
        self.assertTrue(report.conflicts)

    def test_missing_subject_dropped(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            {"predicate": "x", "object": 1},
        ])
        self.assertEqual(report.claims_examined, 0)

    def test_missing_predicate_dropped(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            kv.Claim("p", "", 1, "s"),
        ])
        self.assertEqual(report.claims_examined, 0)


class TestReport(unittest.TestCase):
    def test_by_severity_count(self) -> None:
        v = kv.KnowledgeValidator()
        v.register_range("x", 0, 10)
        report = v.validate([
            kv.Claim("a", "name", "foo", "s1", 0.9),
            kv.Claim("a", "name", "bar", "s2", 0.85),
            kv.Claim("b", "x", 99, "s1"),
        ])
        sev = report.by_severity()
        self.assertGreaterEqual(sev["high"], 1)
        self.assertGreaterEqual(sev["medium"], 1)

    def test_report_as_dict(self) -> None:
        v = kv.KnowledgeValidator()
        report = v.validate([
            kv.Claim("a", "x", 1, "s1", 0.9),
            kv.Claim("a", "x", 2, "s2", 0.5),
        ])
        d = report.as_dict()
        self.assertIn("conflicts", d)
        self.assertIn("by_severity", d)


class TestSorting(unittest.TestCase):
    def test_high_severity_first(self) -> None:
        v = kv.KnowledgeValidator()
        v.register_range("x", 0, 10)
        report = v.validate([
            kv.Claim("a", "x", 99, "s"),                # medium range
            kv.Claim("b", "name", "a", "s1", 0.95),
            kv.Claim("b", "name", "b", "s2", 0.9),      # high direct
        ])
        self.assertEqual(report.conflicts[0].severity, "high")


if __name__ == "__main__":
    unittest.main()
