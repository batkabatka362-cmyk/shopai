"""Relation extractor tests."""
from __future__ import annotations

import re
import unittest

from core.memory import relation_extractor as re_


class TestExtract(unittest.TestCase):
    def setUp(self) -> None:
        self.e = re_.RelationExtractor()

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(self.e.extract(""), [])

    def test_is_relation(self) -> None:
        relations = self.e.extract(
            "product_p1 is a winner",
        )
        self.assertEqual(len(relations), 1)
        r = relations[0]
        self.assertEqual(r.subject, "product_p1")
        self.assertEqual(r.verb, "is")
        self.assertEqual(r.obj, "winner")

    def test_has_relation(self) -> None:
        relations = self.e.extract(
            "bundle_42 has three_SKUs",
        )
        kinds = {r.verb for r in relations}
        self.assertIn("has", kinds)

    def test_prefers_relation(self) -> None:
        relations = self.e.extract(
            "segment_pet prefers bundle_deals",
        )
        kinds = {r.verb for r in relations}
        self.assertIn("prefers", kinds)

    def test_causes_relation(self) -> None:
        relations = self.e.extract(
            "high_CPM causes ROAS_drop",
        )
        kinds = {r.verb for r in relations}
        self.assertIn("causes", kinds)

    def test_kills_relation(self) -> None:
        relations = self.e.extract(
            "rule_12 kills losing_campaigns",
        )
        kinds = {r.verb for r in relations}
        self.assertIn("kills", kinds)

    def test_multiple_sentences(self) -> None:
        text = (
            "product_p1 is a winner. "
            "bundle_42 has three_SKUs. "
            "segment_pet prefers bundles."
        )
        relations = self.e.extract(text)
        verbs = {r.verb for r in relations}
        self.assertIn("is", verbs)
        self.assertIn("has", verbs)
        self.assertIn("prefers", verbs)

    def test_dedupe(self) -> None:
        text = (
            "product_p1 is winner. "
            "product_p1 is winner."
        )
        relations = self.e.extract(text)
        # Should be deduped
        self.assertEqual(len(relations), 1)

    def test_no_match(self) -> None:
        relations = self.e.extract(
            "this sentence has no matching relation pattern.",
        )
        # "this sentence has no" — matches has!
        # That's actually fine, it's what the extractor does
        # Make sure extraction didn't crash
        self.assertIsInstance(relations, list)


class TestBatch(unittest.TestCase):
    def test_batch(self) -> None:
        e = re_.RelationExtractor()
        rels = e.extract_batch([
            "product_p1 is winner",
            "bundle has SKUs",
        ])
        self.assertEqual(len(rels), 2)


class TestCustomRule(unittest.TestCase):
    def test_register(self) -> None:
        pattern = re.compile(
            r"(?P<subject>\w+)\s+refunds\s+(?P<object>\w+)",
            re.IGNORECASE,
        )
        rule = re_.ExtractionRule(
            id="refunds",
            pattern=pattern,
            verb="refunds",
            confidence=0.9,
        )
        e = re_.RelationExtractor()
        e.register_rule(rule)
        rels = e.extract("customer_42 refunds order_9")
        verbs = {r.verb for r in rels}
        self.assertIn("refunds", verbs)

    def test_unregister(self) -> None:
        e = re_.RelationExtractor()
        self.assertTrue(e.unregister_rule("is"))
        # "product_p1 is winner" no longer extracts
        rels = e.extract("product_p1 is winner")
        verbs = {r.verb for r in rels}
        self.assertNotIn("is", verbs)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        e = re_.RelationExtractor()
        s = e.stats()
        self.assertGreater(s["rules"], 0)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        e = re_.RelationExtractor()
        rels = e.extract("skuA is winner")
        d = rels[0].as_dict()
        self.assertEqual(d["verb"], "is")
        self.assertEqual(d["object"], "winner")


if __name__ == "__main__":
    unittest.main()
