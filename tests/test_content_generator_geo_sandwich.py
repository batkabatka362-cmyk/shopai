"""Tests for ContentGenerator ↔ quote_sandwich wire-in (Wave E-2)."""
from __future__ import annotations

import unittest

from core.intelligence.content_generator import ContentGenerator


def _product(**kw):
    defaults = dict(
        name="Pet Slow Feeder Bowl",
        price=29.99,
        category="pet",
        features=["silicone grip", "dishwasher safe"],
        benefits=["prevents bloat", "reduces mess"],
    )
    defaults.update(kw)
    return defaults


def _citation(**kw):
    defaults = dict(
        claim="Slow feeders cut bloat by 40%.",
        quote="Dogs that eat slowly digest better.",
        source_name="Dr. Elena Martinez",
        source_type="expert",
        citation="AVMA Journal 2024",
    )
    defaults.update(kw)
    return defaults


class TestFlagDefaultOff(unittest.TestCase):
    def test_default_behaviour_unchanged(self):
        gen = ContentGenerator()
        out = gen.product_description(_product())
        self.assertNotIn("geo_sandwiches", out)
        self.assertNotIn("body_html", out)
        self.assertIn("body", out)

    def test_flag_off_with_citations_ignored(self):
        gen = ContentGenerator()
        out = gen.product_description(
            _product(citations=[_citation()]),
        )
        # Flag not passed → citations ignored
        self.assertNotIn("geo_sandwiches", out)


class TestFlagOn(unittest.TestCase):
    def test_missing_citations_no_sandwich(self):
        gen = ContentGenerator()
        out = gen.product_description(
            _product(),
            use_geo_sandwich=True,
        )
        # Flag on but no citations → no fake content
        self.assertNotIn("geo_sandwiches", out)
        self.assertNotIn("body_html", out)

    def test_empty_citations_list_no_sandwich(self):
        gen = ContentGenerator()
        out = gen.product_description(
            _product(citations=[]),
            use_geo_sandwich=True,
        )
        self.assertNotIn("geo_sandwiches", out)

    def test_citations_emit_sandwich(self):
        gen = ContentGenerator()
        out = gen.product_description(
            _product(citations=[_citation()]),
            use_geo_sandwich=True,
        )
        self.assertIn("geo_sandwiches", out)
        self.assertEqual(len(out["geo_sandwiches"]), 1)
        self.assertIn("body_html", out)
        self.assertIn(
            "Slow feeders cut bloat by 40%.",
            out["body_html"],
        )
        self.assertIn(
            "Dr. Elena Martinez", out["body_html"],
        )

    def test_multiple_citations_all_wrapped(self):
        gen = ContentGenerator()
        citations = [
            _citation(),
            _citation(
                claim="Silicone bowls are dishwasher safe.",
                quote="Food-grade silicone is safe above 200°C.",
                source_name="FDA Food Contact Materials, 2023",
                source_type="research",
            ),
        ]
        out = gen.product_description(
            _product(citations=citations),
            use_geo_sandwich=True,
        )
        self.assertEqual(len(out["geo_sandwiches"]), 2)
        self.assertIn(
            "dishwasher safe", out["body_html"],
        )
        self.assertIn(
            "FDA Food Contact Materials",
            out["body_html"],
        )


class TestMalformedCitations(unittest.TestCase):
    def test_malformed_citation_skipped(self):
        gen = ContentGenerator()
        citations = [
            _citation(),
            {"claim": "", "quote": "q"},  # invalid
            "not a dict",
            _citation(claim="Second valid.", quote="q2"),
        ]
        out = gen.product_description(
            _product(citations=citations),
            use_geo_sandwich=True,
        )
        self.assertEqual(len(out["geo_sandwiches"]), 2)

    def test_non_list_citations_ignored(self):
        gen = ContentGenerator()
        out = gen.product_description(
            _product(citations="not a list"),
            use_geo_sandwich=True,
        )
        self.assertNotIn("geo_sandwiches", out)


class TestCoreFieldsPreserved(unittest.TestCase):
    def test_standard_fields_still_present_with_sandwich(self):
        gen = ContentGenerator()
        out = gen.product_description(
            _product(citations=[_citation()]),
            use_geo_sandwich=True,
        )
        for key in (
            "headline", "subheadline", "body",
            "bullet_points", "meta_description",
            "meta_title", "cta_primary", "cta_secondary",
            "word_count", "tone",
        ):
            self.assertIn(key, out)


if __name__ == "__main__":
    unittest.main()
