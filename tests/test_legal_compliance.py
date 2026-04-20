"""Tests for core.legal.compliance — region-aware legal pages."""
from __future__ import annotations

import unittest

from core.legal.compliance import (
    LegalPage,
    LegalPageSet,
    REGION_EU,
    REGION_UK,
    REGION_US,
    render_legal_pages,
)


def _set(**overrides):
    kw = dict(
        store_name="Hedgehog Store",
        contact_email="hi@hedgehog.test",
        region=REGION_US,
    )
    kw.update(overrides)
    return render_legal_pages(**kw)


class TestValidation(unittest.TestCase):
    def test_blank_store_raises(self):
        with self.assertRaises(ValueError):
            render_legal_pages(
                store_name="",
                contact_email="x@y.com",
            )

    def test_bad_email_raises(self):
        with self.assertRaises(ValueError):
            render_legal_pages(
                store_name="s",
                contact_email="not-an-email",
            )

    def test_invalid_region_raises(self):
        with self.assertRaises(ValueError):
            render_legal_pages(
                store_name="s",
                contact_email="x@y.com",
                region="ZZ",
            )


class TestRendering(unittest.TestCase):
    def test_five_pages_rendered_by_default(self):
        out = _set()
        kinds = {p.kind for p in out.pages}
        self.assertEqual(
            kinds,
            {
                "privacy", "terms", "returns",
                "shipping", "cookies",
            },
        )

    def test_include_filters(self):
        out = _set(include=("privacy", "terms"))
        kinds = [p.kind for p in out.pages]
        self.assertEqual(kinds, ["privacy", "terms"])

    def test_unknown_include_silently_skipped(self):
        out = _set(include=("privacy", "nonsense"))
        kinds = [p.kind for p in out.pages]
        self.assertEqual(kinds, ["privacy"])

    def test_store_name_in_every_page(self):
        out = _set()
        for p in out.pages:
            self.assertIn(
                "Hedgehog Store", p.markdown,
            )

    def test_contact_email_in_every_page(self):
        out = _set()
        for p in out.pages:
            self.assertIn(
                "hi@hedgehog.test", p.markdown,
            )


class TestRegionalLanguage(unittest.TestCase):
    def test_us_privacy_mentions_ccpa(self):
        privacy = _set(
            region=REGION_US, include=("privacy",),
        ).get("privacy")
        self.assertIn("CCPA", privacy.markdown)
        self.assertNotIn("GDPR", privacy.markdown)

    def test_eu_privacy_mentions_gdpr(self):
        privacy = _set(
            region=REGION_EU, include=("privacy",),
        ).get("privacy")
        self.assertIn("GDPR", privacy.markdown)

    def test_uk_privacy_mentions_uk_ico(self):
        privacy = _set(
            region=REGION_UK, include=("privacy",),
        ).get("privacy")
        self.assertIn("ICO", privacy.markdown)

    def test_eu_returns_has_14_day_cooling_off(self):
        returns = _set(
            region=REGION_EU, include=("returns",),
        ).get("returns")
        self.assertIn("14 days", returns.markdown)
        self.assertIn("cooling-off", returns.markdown)

    def test_us_returns_has_30_day_window(self):
        returns = _set(
            region=REGION_US, include=("returns",),
        ).get("returns")
        self.assertIn("30 days", returns.markdown)
        self.assertNotIn("cooling-off", returns.markdown)

    def test_eu_cookies_mentions_eprivacy(self):
        cookies = _set(
            region=REGION_EU, include=("cookies",),
        ).get("cookies")
        self.assertIn("ePrivacy", cookies.markdown)

    def test_terms_governing_law_by_region(self):
        self.assertIn(
            "Delaware",
            _set(region=REGION_US, include=("terms",))
            .get("terms").markdown,
        )
        self.assertIn(
            "Ireland",
            _set(region=REGION_EU, include=("terms",))
            .get("terms").markdown,
        )
        self.assertIn(
            "England and Wales",
            _set(region=REGION_UK, include=("terms",))
            .get("terms").markdown,
        )


class TestCustomSections(unittest.TestCase):
    def test_custom_replaces_template(self):
        out = _set(
            custom_sections={
                "privacy": "# Custom Privacy\n\nOur text.",
            },
        )
        privacy = out.get("privacy")
        self.assertIn("Custom Privacy", privacy.markdown)
        self.assertNotIn("CCPA", privacy.markdown)

    def test_custom_only_affects_that_kind(self):
        out = _set(
            custom_sections={
                "privacy": "x",
            },
        )
        self.assertIn(
            "Terms of Service",
            out.get("terms").markdown,
        )


class TestShape(unittest.TestCase):
    def test_pageset_dict(self):
        out = _set()
        d = out.as_dict()
        self.assertEqual(d["store_name"], "Hedgehog Store")
        self.assertEqual(len(d["pages"]), 5)
        self.assertIn("markdown", d["pages"][0])

    def test_get_missing_returns_none(self):
        out = _set(include=("privacy",))
        self.assertIsNone(out.get("terms"))

    def test_updated_ts_populated(self):
        out = _set()
        for p in out.pages:
            self.assertGreater(p.updated_ts, 0)


if __name__ == "__main__":
    unittest.main()
