"""SEO skill — deterministic product metadata generator.

Sprint 3 S3-4 (P1, L6 in docs/AGI_STACK.md). Given a product dict
(title, description, price, image, etc.) produces a ``ProductSEO``
bundle ready to drop into:

  * Shopify product ``seo_title`` / ``seo_description`` fields
  * Theme ``<meta>`` and Open Graph / Twitter tags
  * ``<script type="application/ld+json">`` schema.org Product node
  * Google Merchant Center feed (via ``build_merchant_feed``)

Every field follows the platform's documented limits:

  * Google title tag    : ≤60 chars (soft cap, longer truncates in SERP)
  * Meta description   : ≤160 chars
  * Open Graph title   : ≤70 chars
  * Merchant feed title: ≤150 chars, description ≤5000 chars

Pure stdlib (only json + html + re). Deterministic — the same input
always produces the same output so regression tests are snapshotable.
LLM-free. No network.

Owner can later plug in an LLM copywriter for the description, but
the deterministic fallback uses sentence-aware truncation so the
brain isn't blocked on LLM credits to publish a product.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable


_META_TITLE_MAX = 60
_META_DESCRIPTION_MAX = 160
_OG_TITLE_MAX = 70
_MERCHANT_TITLE_MAX = 150
_MERCHANT_DESCRIPTION_MAX = 5000


@dataclass
class ProductSEO:
    meta_title: str
    meta_description: str
    og_title: str
    og_description: str
    og_image: str
    og_url: str
    twitter_card: str
    twitter_title: str
    twitter_description: str
    twitter_image: str
    schema_org_jsonld: str              # ready to embed in <script>
    merchant_feed_entry: dict[str, Any]
    keywords: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "meta_title": self.meta_title,
            "meta_description": self.meta_description,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "og_image": self.og_image,
            "og_url": self.og_url,
            "twitter_card": self.twitter_card,
            "twitter_title": self.twitter_title,
            "twitter_description": self.twitter_description,
            "twitter_image": self.twitter_image,
            "schema_org_jsonld": self.schema_org_jsonld,
            "merchant_feed_entry": dict(
                self.merchant_feed_entry,
            ),
            "keywords": list(self.keywords),
        }


# ── Helpers ────────────────────────────────────────────────


def _clean(text: str) -> str:
    """Strip HTML + collapse whitespace."""
    stripped = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", stripped).strip()


def _truncate(text: str, limit: int) -> str:
    """Truncate at nearest word boundary, then character boundary
    as last resort. Adds U+2026 horizontal ellipsis when cut."""
    if limit <= 0:
        return ""
    text = text or ""
    if len(text) <= limit:
        return text
    hard = text[:limit]
    last_space = hard.rfind(" ")
    if last_space >= int(limit * 0.6):
        hard = hard[:last_space]
    return hard.rstrip(" ,.;:-") + "\u2026"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower())
    return slug.strip("-")


def _extract_keywords(
    title: str,
    description: str,
    *,
    max_keywords: int = 8,
    stopwords: frozenset[str] = frozenset({
        "the", "a", "an", "and", "or", "of", "to", "for",
        "with", "in", "on", "at", "is", "are", "was", "were",
        "this", "that", "your", "our", "you", "we", "it",
    }),
) -> tuple[str, ...]:
    text = f"{title} {description}".lower()
    tokens = re.findall(r"[a-z][a-z0-9]+", text)
    seen: dict[str, int] = {}
    for t in tokens:
        if len(t) < 3 or t in stopwords:
            continue
        seen[t] = seen.get(t, 0) + 1
    ranked = sorted(
        seen.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return tuple(k for k, _ in ranked[:max_keywords])


def _build_schema_org(
    *,
    name: str,
    description: str,
    image: str,
    url: str,
    price: float,
    currency: str,
    availability: str,
    sku: str,
    brand: str,
    rating_value: float | None,
    rating_count: int | None,
) -> str:
    node: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "description": description,
        "sku": sku,
        "offers": {
            "@type": "Offer",
            "priceCurrency": currency,
            "price": f"{price:.2f}",
            "availability": (
                f"https://schema.org/{availability}"
            ),
            "url": url,
        },
    }
    if image:
        node["image"] = image
    if brand:
        node["brand"] = {
            "@type": "Brand",
            "name": brand,
        }
    if rating_value is not None and rating_count:
        node["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": f"{float(rating_value):.1f}",
            "reviewCount": int(rating_count),
        }
    return json.dumps(node, separators=(",", ":"))


def _merchant_entry(
    *,
    product_id: str,
    name: str,
    description: str,
    image: str,
    url: str,
    price: float,
    currency: str,
    availability: str,
    brand: str,
    gtin: str,
    mpn: str,
    condition: str,
) -> dict[str, Any]:
    return {
        "id": product_id,
        "title": _truncate(name, _MERCHANT_TITLE_MAX),
        "description": _truncate(
            description, _MERCHANT_DESCRIPTION_MAX,
        ),
        "link": url,
        "image_link": image,
        "availability": availability,
        "price": f"{price:.2f} {currency}",
        "condition": condition,
        "brand": brand or "Generic",
        "gtin": gtin,
        "mpn": mpn or product_id,
        "identifier_exists": bool(gtin or brand),
    }


# ── Public API ─────────────────────────────────────────────


def generate_product_seo(
    product: dict[str, Any],
    *,
    store_name: str,
    site_url: str,
    currency: str = "USD",
    twitter_card_style: str = "summary_large_image",
) -> ProductSEO:
    """Build a ``ProductSEO`` bundle from a product dict.

    Required product keys: ``title``. Everything else is optional
    and defaults to sensible empty values.

    Supported product keys:
      * title            (str, required)
      * description      (str)
      * image / image_url (str)
      * url / handle     (str)
      * price            (float)
      * sku / id         (str)
      * brand            (str)
      * availability     ("InStock" | "OutOfStock" | ...)
      * condition        ("new" | "used" | "refurbished")
      * gtin / mpn       (str) — boosts Merchant Center match rate
      * rating / review_count (float / int) — schema aggregateRating
    """
    title = str(product.get("title") or "").strip()
    if not title:
        raise ValueError("product.title required")
    description = _clean(
        product.get("description") or title,
    )
    image = str(
        product.get("image")
        or product.get("image_url")
        or "",
    )
    price = float(product.get("price") or 0.0)
    sku = str(
        product.get("sku") or product.get("id") or "",
    )
    brand = str(
        product.get("brand") or store_name or "",
    ).strip()
    handle = str(
        product.get("url")
        or product.get("handle")
        or _slugify(title),
    )
    if handle.startswith("http"):
        product_url = handle
    else:
        base = (site_url or "").rstrip("/")
        suffix = handle.lstrip("/")
        product_url = f"{base}/{suffix}" if base else suffix
    availability_raw = str(
        product.get("availability") or "InStock",
    )
    availability_schema = availability_raw
    # Google Merchant expects lowercase "in stock" / "out of stock"
    availability_merchant = {
        "InStock": "in stock",
        "OutOfStock": "out of stock",
        "PreOrder": "preorder",
        "BackOrder": "backorder",
    }.get(availability_raw, "in stock")
    condition = str(product.get("condition") or "new")

    # Titles
    meta_title = _truncate(
        f"{title} — {store_name}" if store_name else title,
        _META_TITLE_MAX,
    )
    og_title = _truncate(title, _OG_TITLE_MAX)

    # Descriptions
    meta_description = _truncate(
        description, _META_DESCRIPTION_MAX,
    )
    og_description = meta_description
    twitter_description = meta_description

    # Schema.org
    rating_value = product.get("rating")
    rating_count = product.get("review_count")
    schema_jsonld = _build_schema_org(
        name=title,
        description=description,
        image=image,
        url=product_url,
        price=price,
        currency=currency,
        availability=availability_schema,
        sku=sku,
        brand=brand,
        rating_value=(
            float(rating_value)
            if rating_value is not None else None
        ),
        rating_count=(
            int(rating_count)
            if rating_count is not None else None
        ),
    )

    # Merchant feed entry
    merchant = _merchant_entry(
        product_id=sku or _slugify(title),
        name=title,
        description=description,
        image=image,
        url=product_url,
        price=price,
        currency=currency,
        availability=availability_merchant,
        brand=brand,
        gtin=str(product.get("gtin") or ""),
        mpn=str(product.get("mpn") or ""),
        condition=condition,
    )

    keywords = _extract_keywords(title, description)

    return ProductSEO(
        meta_title=meta_title,
        meta_description=meta_description,
        og_title=og_title,
        og_description=og_description,
        og_image=image,
        og_url=product_url,
        twitter_card=twitter_card_style,
        twitter_title=og_title,
        twitter_description=twitter_description,
        twitter_image=image,
        schema_org_jsonld=schema_jsonld,
        merchant_feed_entry=merchant,
        keywords=keywords,
    )


def build_merchant_feed(
    entries: Iterable[dict[str, Any]],
    *,
    feed_title: str = "ShopAI Product Feed",
    feed_link: str = "",
    feed_description: str = "",
) -> str:
    """Build a Google Merchant Center XML feed from pre-built
    entries (typically ``ProductSEO.merchant_feed_entry`` dicts).

    Produces the Atom-based ``g:`` namespace feed that Merchant
    Center ingests natively. Strings are HTML-escaped.
    """

    def _el(tag: str, text: Any) -> str:
        return (
            f"    <{tag}>"
            f"{html.escape(str(text))}"
            f"</{tag}>"
        )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" '
        'xmlns:g="http://base.google.com/ns/1.0">',
        "<channel>",
        f"  <title>{html.escape(feed_title)}</title>",
        f"  <link>{html.escape(feed_link)}</link>",
        (
            f"  <description>"
            f"{html.escape(feed_description)}"
            f"</description>"
        ),
    ]
    for entry in entries:
        lines.append("  <item>")
        for key, tag in (
            ("id", "g:id"),
            ("title", "title"),
            ("description", "description"),
            ("link", "link"),
            ("image_link", "g:image_link"),
            ("availability", "g:availability"),
            ("price", "g:price"),
            ("condition", "g:condition"),
            ("brand", "g:brand"),
        ):
            value = entry.get(key, "")
            if value:
                lines.append(_el(tag, value))
        # Optional identifier trio
        gtin = entry.get("gtin", "")
        if gtin:
            lines.append(_el("g:gtin", gtin))
        mpn = entry.get("mpn", "")
        if mpn:
            lines.append(_el("g:mpn", mpn))
        lines.append(
            _el(
                "g:identifier_exists",
                "yes"
                if entry.get("identifier_exists")
                else "no",
            ),
        )
        lines.append("  </item>")
    lines.append("</channel>")
    lines.append("</rss>")
    return "\n".join(lines)
