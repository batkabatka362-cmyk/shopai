"""Tests for execution.seo.schema_stack + llms_txt (Wave E-1)."""
from __future__ import annotations

import json
import unittest

from execution.seo.schema_stack import (
    AuthorEntity,
    SchemaStack,
    build_schema_stack,
)
from execution.seo.llms_txt import (
    LLMTxtIndex,
    build_llms_txt,
    build_markdown_mirror,
)


def _author():
    return AuthorEntity(
        entity_id="https://hedgehog.shop/#publisher",
        name="Hedgehog Store",
        kind="Organization",
        same_as=(
            "https://linkedin.com/company/hedgehog",
            "https://wikidata.org/wiki/Q123",
        ),
        url="https://hedgehog.shop",
    )


def _product(**overrides):
    p = {
        "title": "Pet Slow Feeder",
        "handle": "pet-slow-feeder",
        "description": "Reduces eating speed for dogs.",
        "price": 29.99,
        "currency": "USD",
        "sku": "PET-001",
        "brand": "Hedgehog",
        "image": "https://cdn.shop/1.jpg",
        "rating": 4.6,
        "review_count": 120,
        "availability": "InStock",
    }
    p.update(overrides)
    return p


# ── Schema stack tests ─────────────────────────────────────


class TestSchemaStackValidation(unittest.TestCase):
    def test_missing_title_raises(self):
        with self.assertRaises(ValueError):
            build_schema_stack(
                {},
                site_url="https://x",
                author=_author(),
            )


class TestSchemaStackTypes(unittest.TestCase):
    def test_minimum_three_types(self):
        # Zero-extras case still emits Product + Organization
        # + Brand + Offer + Author → ≥3 types
        stack = build_schema_stack(
            _product(rating=None, review_count=None),
            site_url="https://hedgehog.shop",
            author=_author(),
        )
        types = set(stack.types())
        self.assertTrue(
            {"Product", "Organization", "Brand",
             "Offer"}.issubset(types),
        )

    def test_rating_included(self):
        stack = build_schema_stack(
            _product(),
            site_url="https://hedgehog.shop",
            author=_author(),
        )
        self.assertIn("AggregateRating", stack.types())

    def test_faq_included(self):
        stack = build_schema_stack(
            _product(),
            site_url="https://hedgehog.shop",
            author=_author(),
            faqs=[
                {
                    "q": "Is it dishwasher safe?",
                    "a": "Top rack safe.",
                },
            ],
        )
        self.assertIn("FAQPage", stack.types())

    def test_howto_included(self):
        stack = build_schema_stack(
            _product(),
            site_url="https://hedgehog.shop",
            author=_author(),
            howto_steps=["Rinse", "Fill", "Serve"],
        )
        self.assertIn("HowTo", stack.types())

    def test_video_included(self):
        stack = build_schema_stack(
            _product(),
            site_url="https://hedgehog.shop",
            author=_author(),
            video={
                "content_url": "https://cdn.shop/v.mp4",
                "name": "demo",
                "upload_date": "2026-04-20",
            },
        )
        self.assertIn("VideoObject", stack.types())

    def test_breadcrumbs_included(self):
        stack = build_schema_stack(
            _product(),
            site_url="https://hedgehog.shop",
            author=_author(),
            breadcrumbs=[
                {"name": "Home", "url": "https://x/"},
                {"name": "Pets", "url": "https://x/pets"},
            ],
        )
        self.assertIn("BreadcrumbList", stack.types())

    def test_organization_overrides(self):
        stack = build_schema_stack(
            _product(),
            site_url="https://hedgehog.shop",
            author=_author(),
            organization={
                "name": "Custom Org",
                "same_as": [
                    "https://twitter.com/custom",
                ],
            },
        )
        org = next(
            n for n in stack.graph
            if n.get("@type") == "Organization"
        )
        self.assertEqual(org["name"], "Custom Org")
        self.assertIn(
            "https://twitter.com/custom",
            org.get("sameAs", []),
        )


class TestSchemaStackOutput(unittest.TestCase):
    def test_script_tag_is_valid_json(self):
        stack = build_schema_stack(
            _product(),
            site_url="https://hedgehog.shop",
            author=_author(),
        )
        s = stack.as_script_tag()
        parsed = json.loads(s)
        self.assertEqual(
            parsed["@context"], "https://schema.org",
        )
        self.assertIsInstance(parsed["@graph"], list)

    def test_product_references_brand_and_offer(self):
        stack = build_schema_stack(
            _product(),
            site_url="https://hedgehog.shop",
            author=_author(),
        )
        product = next(
            n for n in stack.graph
            if n.get("@type") == "Product"
        )
        self.assertIn("brand", product)
        self.assertIn("offers", product)
        self.assertEqual(
            product["author"]["@id"],
            _author().entity_id,
        )

    def test_offer_price_formatted(self):
        stack = build_schema_stack(
            _product(price=30),
            site_url="https://hedgehog.shop",
            author=_author(),
        )
        offer = next(
            n for n in stack.graph
            if n.get("@type") == "Offer"
        )
        self.assertEqual(offer["price"], "30.00")
        self.assertEqual(
            offer["availability"],
            "https://schema.org/InStock",
        )


class TestAuthorEntity(unittest.TestCase):
    def test_jsonld_shape(self):
        j = _author().as_jsonld()
        self.assertEqual(j["@type"], "Organization")
        self.assertEqual(
            j["@id"],
            "https://hedgehog.shop/#publisher",
        )
        self.assertIn(
            "https://linkedin.com/company/hedgehog",
            j["sameAs"],
        )

    def test_dict(self):
        d = _author().as_dict()
        self.assertEqual(d["kind"], "Organization")

    def test_person_kind(self):
        a = AuthorEntity(
            entity_id="#x", name="Alice",
            kind="Person", url="https://a.com",
        )
        j = a.as_jsonld()
        self.assertEqual(j["@type"], "Person")


# ── llms.txt tests ─────────────────────────────────────────


class TestMarkdownMirror(unittest.TestCase):
    def test_basic_shape(self):
        path, body = build_markdown_mirror(
            _product(),
            store_url="https://hedgehog.shop",
        )
        self.assertEqual(
            path, "products/pet-slow-feeder.md",
        )
        self.assertIn("# Pet Slow Feeder", body)
        self.assertIn(
            "https://hedgehog.shop/products/pet-slow-feeder",
            body,
        )
        self.assertIn("Price: $29.99", body)

    def test_faqs_rendered(self):
        _, body = build_markdown_mirror(
            _product(faqs=[
                {
                    "q": "Machine wash?",
                    "a": "Top-rack only.",
                },
            ]),
            store_url="https://x",
        )
        self.assertIn("## FAQ", body)
        self.assertIn("Machine wash?", body)

    def test_highlights_rendered(self):
        _, body = build_markdown_mirror(
            _product(highlights=[
                "Reduces bloat",
                "Dishwasher safe",
            ]),
            store_url="https://x",
        )
        self.assertIn("## Highlights", body)
        self.assertIn("- Reduces bloat", body)


class TestLLMTxt(unittest.TestCase):
    def test_blank_name_raises(self):
        with self.assertRaises(ValueError):
            build_llms_txt(
                store_name="",
                store_url="https://x",
                products=[],
            )

    def test_minimal_build(self):
        idx = build_llms_txt(
            store_name="Hedgehog",
            store_url="https://hedgehog.shop",
            products=[_product()],
            summary="Pet supplies store.",
        )
        self.assertIn("# Hedgehog", idx.short_txt)
        self.assertIn(
            "> Pet supplies store.", idx.short_txt,
        )
        self.assertIn(
            "[Pet Slow Feeder]", idx.short_txt,
        )
        self.assertIn("## Products", idx.short_txt)
        self.assertIn("## Policies", idx.short_txt)

    def test_full_txt_includes_products(self):
        idx = build_llms_txt(
            store_name="Hedgehog",
            store_url="https://hedgehog.shop",
            products=[_product()],
        )
        self.assertIn(
            "# Pet Slow Feeder", idx.full_txt,
        )

    def test_full_txt_disabled(self):
        idx = build_llms_txt(
            store_name="H",
            store_url="https://x",
            products=[_product()],
            include_full=False,
        )
        self.assertEqual(idx.full_txt, "")

    def test_mirror_count_matches(self):
        idx = build_llms_txt(
            store_name="H",
            store_url="https://x",
            products=[
                _product(title="A", handle="a"),
                _product(title="B", handle="b"),
            ],
        )
        self.assertEqual(len(idx.product_mirrors), 2)

    def test_empty_products(self):
        idx = build_llms_txt(
            store_name="Empty",
            store_url="https://empty.com",
            products=[],
        )
        self.assertEqual(
            len(idx.product_mirrors), 0,
        )
        self.assertIn("Empty", idx.short_txt)

    def test_dict(self):
        idx = build_llms_txt(
            store_name="H",
            store_url="https://x",
            products=[_product()],
        )
        d = idx.as_dict()
        self.assertIn("short_txt_chars", d)
        self.assertEqual(d["mirror_count"], 1)


class TestSchemaStackDict(unittest.TestCase):
    def test_dict_counts_unique_types(self):
        stack = build_schema_stack(
            _product(),
            site_url="https://x",
            author=_author(),
        )
        d = stack.as_dict()
        self.assertGreaterEqual(d["type_count"], 3)


if __name__ == "__main__":
    unittest.main()
