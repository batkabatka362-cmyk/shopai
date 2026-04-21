"""Tests for execution.seo.quote_sandwich — Princeton GEO formatter."""
from __future__ import annotations

import unittest

from execution.seo.quote_sandwich import (
    Sandwich,
    wrap_claim,
    wrap_many,
)


class TestValidation(unittest.TestCase):
    def test_empty_claim_raises(self):
        with self.assertRaises(ValueError):
            wrap_claim(claim="", quote="q")

    def test_whitespace_claim_raises(self):
        with self.assertRaises(ValueError):
            wrap_claim(claim="   ", quote="q")

    def test_empty_quote_raises(self):
        with self.assertRaises(ValueError):
            wrap_claim(claim="c", quote="")

    def test_unknown_source_type_becomes_generic(self):
        s = wrap_claim(
            claim="c", quote="q",
            source_name="Foo",
            source_type="astrologer",
        )
        self.assertEqual(s.source_type, "generic")


class TestShape(unittest.TestCase):
    def _basic(self):
        return wrap_claim(
            claim="Slow feeders cut bloat by 40%.",
            quote="Dogs that eat slowly digest better.",
            source_name="Dr. Elena Martinez",
            source_type="expert",
            citation="AVMA Journal 2024",
            citation_url="https://avma.example.com/bloat",
        )

    def test_returns_sandwich_dataclass(self):
        s = self._basic()
        self.assertIsInstance(s, Sandwich)
        self.assertEqual(
            s.claim, "Slow feeders cut bloat by 40%.",
        )
        self.assertEqual(
            s.source_name, "Dr. Elena Martinez",
        )
        self.assertEqual(s.source_type, "expert")

    def test_html_contains_all_three_parts(self):
        s = self._basic()
        html = s.as_dict()["html"]
        self.assertIn("<blockquote", html)
        self.assertIn(
            "According to Dr. Elena Martinez", html,
        )
        self.assertIn(
            "Dogs that eat slowly digest better", html,
        )
        self.assertIn(
            "Slow feeders cut bloat by 40%.", html,
        )
        self.assertIn("<cite>", html)
        self.assertIn(
            'href="https://avma.example.com/bloat"', html,
        )

    def test_html_has_proper_quote_ordering(self):
        """Sandwich order: quote → claim → citation."""
        s = self._basic()
        html = s.as_dict()["html"]
        blockquote_idx = html.find("<blockquote")
        claim_idx = html.find(
            "Slow feeders cut bloat by 40%.",
        )
        cite_idx = html.find("<cite>")
        self.assertLess(blockquote_idx, claim_idx)
        self.assertLess(claim_idx, cite_idx)


class TestSourceTypes(unittest.TestCase):
    def test_expert_lead_in(self):
        s = wrap_claim(
            claim="c", quote="q",
            source_name="Dr. X", source_type="expert",
        )
        self.assertIn(
            "According to Dr. X", s.as_dict()["html"],
        )

    def test_research_lead_in(self):
        s = wrap_claim(
            claim="c", quote="q",
            source_name="Princeton Lab",
            source_type="research",
        )
        self.assertIn(
            "Research from Princeton Lab",
            s.as_dict()["html"],
        )

    def test_reviewer_lead_in(self):
        s = wrap_claim(
            claim="c", quote="q",
            source_name="Anna",
            source_type="reviewer",
        )
        self.assertIn(
            "As one customer put it",
            s.as_dict()["html"],
        )

    def test_missing_source_name_defaults(self):
        s = wrap_claim(
            claim="c", quote="q",
            source_type="expert",
        )
        # falls back to "industry research"
        self.assertIn(
            "industry research",
            s.as_dict()["html"],
        )


class TestEscaping(unittest.TestCase):
    def test_html_in_claim_escaped(self):
        s = wrap_claim(
            claim="<script>alert('x')</script>",
            quote="q",
            source_name="s",
        )
        html = s.as_dict()["html"]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_html_in_quote_escaped(self):
        s = wrap_claim(
            claim="c",
            quote="<img onerror=evil>",
            source_name="s",
        )
        html = s.as_dict()["html"]
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)

    def test_citation_url_quote_escaped(self):
        s = wrap_claim(
            claim="c", quote="q",
            citation="src",
            citation_url='"onclick=evil',
        )
        html = s.as_dict()["html"]
        # href attribute quotes must stay balanced
        self.assertIn(
            'href="&quot;onclick=evil"', html,
        )


class TestOptional(unittest.TestCase):
    def test_no_citation_omits_cite_element(self):
        s = wrap_claim(
            claim="c", quote="q", source_name="s",
        )
        self.assertNotIn("<cite>", s.as_dict()["html"])

    def test_citation_without_url(self):
        s = wrap_claim(
            claim="c", quote="q",
            source_name="s",
            citation="Journal",
        )
        html = s.as_dict()["html"]
        self.assertIn("<cite>Journal</cite>", html)
        self.assertNotIn("<a href=", html)


class TestWrapMany(unittest.TestCase):
    def test_batch_wrap(self):
        claims = [
            {
                "claim": "First claim.",
                "quote": "First quote.",
                "source_name": "A",
            },
            {
                "claim": "Second claim.",
                "quote": "Second quote.",
                "source_name": "B",
            },
        ]
        sandwiches = wrap_many(claims)
        self.assertEqual(len(sandwiches), 2)
        self.assertEqual(
            sandwiches[0].source_name, "A",
        )

    def test_malformed_entries_skipped(self):
        claims = [
            {"claim": "ok", "quote": "ok"},
            "not a dict",
            {"claim": "", "quote": "q"},  # validation fails
            {"bogus": "field"},  # missing required
            {"claim": "also ok", "quote": "q"},
        ]
        sandwiches = wrap_many(claims)  # type: ignore[arg-type]
        self.assertEqual(len(sandwiches), 2)

    def test_empty_list(self):
        self.assertEqual(wrap_many([]), [])
        self.assertEqual(wrap_many(None), [])  # type: ignore[arg-type]


class TestAsDict(unittest.TestCase):
    def test_round_trip(self):
        s = wrap_claim(
            claim="c", quote="q",
            source_name="s", source_type="expert",
            citation="cit",
        )
        d = s.as_dict()
        self.assertEqual(d["claim"], "c")
        self.assertEqual(d["quote"], "q")
        self.assertEqual(d["source_name"], "s")
        self.assertEqual(d["source_type"], "expert")
        self.assertEqual(d["citation"], "cit")
        self.assertIn("html", d)


if __name__ == "__main__":
    unittest.main()
