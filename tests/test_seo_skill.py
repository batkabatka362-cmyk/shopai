"""Tests for execution.seo.seo_skill."""
from __future__ import annotations

import json
import unittest
from xml.etree import ElementTree as ET

from execution.seo.seo_skill import (
    ProductSEO,
    build_merchant_feed,
    generate_product_seo,
)


def _gen(**overrides):
    product = {
        "title": "Stainless Steel Pet Slow Feeder",
        "description": (
            "<p>Reduces your dog's eating speed for "
            "healthier digestion.</p>"
        ),
        "image": "https://cdn.shop/img/1.jpg",
        "price": 29.99,
        "sku": "PET-001",
        "brand": "Hedgehog",
        "availability": "InStock",
        "gtin": "1234567890123",
    }
    product.update(overrides)
    return generate_product_seo(
        product,
        store_name="Hedgehog Store",
        site_url="https://hedgehog.shop",
        currency="USD",
    )


class TestValidation(unittest.TestCase):
    def test_missing_title_raises(self):
        with self.assertRaises(ValueError):
            generate_product_seo(
                {"description": "x"},
                store_name="s", site_url="",
            )

    def test_blank_title_raises(self):
        with self.assertRaises(ValueError):
            generate_product_seo(
                {"title": "  "},
                store_name="s", site_url="",
            )


class TestMetaTitleDescription(unittest.TestCase):
    def test_meta_title_under_60_chars(self):
        seo = _gen()
        self.assertLessEqual(len(seo.meta_title), 60)

    def test_meta_title_includes_store_name(self):
        seo = _gen()
        self.assertIn("Hedgehog Store", seo.meta_title)

    def test_meta_description_under_160_chars(self):
        seo = _gen(
            description="x " * 200,
        )
        self.assertLessEqual(
            len(seo.meta_description), 160,
        )

    def test_html_stripped_from_description(self):
        seo = _gen()
        self.assertNotIn("<p>", seo.meta_description)
        self.assertIn("dog", seo.meta_description.lower())


class TestOpenGraph(unittest.TestCase):
    def test_og_image_populated(self):
        seo = _gen()
        self.assertEqual(
            seo.og_image, "https://cdn.shop/img/1.jpg",
        )

    def test_og_url_combines_site_and_handle(self):
        seo = _gen(handle="products/slow-feeder")
        self.assertEqual(
            seo.og_url,
            "https://hedgehog.shop/products/slow-feeder",
        )

    def test_og_url_absolute_url_preserved(self):
        seo = _gen(url="https://other.shop/p/1")
        self.assertEqual(
            seo.og_url, "https://other.shop/p/1",
        )

    def test_og_title_under_70_chars(self):
        seo = _gen(title="A" * 200)
        self.assertLessEqual(len(seo.og_title), 71)   # +1 for ellipsis

    def test_twitter_card_default(self):
        seo = _gen()
        self.assertEqual(
            seo.twitter_card, "summary_large_image",
        )


class TestSchemaOrg(unittest.TestCase):
    def test_schema_is_valid_json(self):
        seo = _gen()
        data = json.loads(seo.schema_org_jsonld)
        self.assertEqual(data["@type"], "Product")
        self.assertEqual(data["offers"]["price"], "29.99")
        self.assertEqual(
            data["offers"]["priceCurrency"], "USD",
        )
        self.assertEqual(
            data["offers"]["availability"],
            "https://schema.org/InStock",
        )

    def test_schema_includes_brand(self):
        seo = _gen()
        data = json.loads(seo.schema_org_jsonld)
        self.assertEqual(
            data["brand"]["name"], "Hedgehog",
        )

    def test_schema_includes_rating_when_present(self):
        seo = _gen(rating=4.6, review_count=123)
        data = json.loads(seo.schema_org_jsonld)
        self.assertEqual(
            data["aggregateRating"]["ratingValue"], "4.6",
        )
        self.assertEqual(
            data["aggregateRating"]["reviewCount"], 123,
        )

    def test_schema_omits_rating_when_missing(self):
        seo = _gen()
        data = json.loads(seo.schema_org_jsonld)
        self.assertNotIn("aggregateRating", data)


class TestMerchantEntry(unittest.TestCase):
    def test_merchant_availability_lowercase(self):
        seo = _gen(availability="OutOfStock")
        self.assertEqual(
            seo.merchant_feed_entry["availability"],
            "out of stock",
        )

    def test_merchant_price_has_currency_suffix(self):
        seo = _gen()
        self.assertEqual(
            seo.merchant_feed_entry["price"],
            "29.99 USD",
        )

    def test_merchant_identifier_exists_with_gtin(self):
        seo = _gen()
        self.assertTrue(
            seo.merchant_feed_entry["identifier_exists"],
        )

    def test_merchant_mpn_falls_back_to_id(self):
        seo = _gen(mpn="")
        self.assertEqual(
            seo.merchant_feed_entry["mpn"], "PET-001",
        )


class TestKeywords(unittest.TestCase):
    def test_keywords_extracted(self):
        seo = _gen()
        # lowercase, no stopwords, no dupes
        self.assertIn("pet", seo.keywords)
        self.assertNotIn("the", seo.keywords)

    def test_keywords_capped(self):
        seo = _gen(
            description=" ".join(
                f"word{i}" for i in range(200)
            ),
        )
        self.assertLessEqual(len(seo.keywords), 8)


class TestMerchantFeedXML(unittest.TestCase):
    def test_build_feed_is_valid_xml(self):
        seo = _gen()
        feed = build_merchant_feed(
            [seo.merchant_feed_entry],
            feed_title="T",
            feed_link="https://hedgehog.shop",
        )
        root = ET.fromstring(feed)
        self.assertEqual(root.tag, "rss")
        items = root.findall("channel/item")
        self.assertEqual(len(items), 1)

    def test_feed_escapes_html(self):
        seo = _gen(
            title="Tools & Gadgets <fancy>",
        )
        feed = build_merchant_feed(
            [seo.merchant_feed_entry],
        )
        # Raw angle brackets / ampersand must be escaped
        self.assertIn("&amp;", feed)
        self.assertIn("&lt;fancy&gt;", feed)

    def test_feed_empty_list(self):
        feed = build_merchant_feed([])
        root = ET.fromstring(feed)
        self.assertEqual(
            len(root.findall("channel/item")), 0,
        )


class TestDict(unittest.TestCase):
    def test_as_dict_serialisable(self):
        seo = _gen()
        d = seo.as_dict()
        json.dumps(d)   # must not raise
        self.assertIn("meta_title", d)
        self.assertIn("merchant_feed_entry", d)


if __name__ == "__main__":
    unittest.main()
