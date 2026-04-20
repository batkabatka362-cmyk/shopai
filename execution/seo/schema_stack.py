"""Schema stack + author entity for AI-era SEO.

Wave E-1 of IMPLEMENTATION_PLAN_2026. The existing ``seo_skill``
emitted a single ``Product`` JSON-LD node. Research shows pages
with ≥3 schema types are +13% more likely to be LLM-cited, and
Feb 2026 Google added an explicit "Authors" section to Search
Central docs — author entity markup via ``@id`` propagates trust
through Knowledge Graph.

This module emits a **stack**: Product + Offer + AggregateRating
+ FAQPage + HowTo + VideoObject + BreadcrumbList + Organization,
all cross-referenced via ``@id`` so crawlers resolve entities
across the graph.

Pure stdlib + json. Deterministic — same product dict always
emits the same JSON-LD stack. LLM-free.

Sources:
  * developers.google.com/search/docs/appearance/structured-data
  * arxiv.org/html/2311.09735v3 (Princeton GEO paper)
  * convertmate.io/research/geo-benchmark-2026
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AuthorEntity:
    """Persistent author entity — one per store. Ship once, reuse
    across every content asset so Knowledge Graph links build up."""
    entity_id: str                 # stable @id
    name: str
    kind: str = "Organization"     # or "Person"
    same_as: tuple[str, ...] = field(default_factory=tuple)
    url: str = ""

    def as_jsonld(self) -> dict[str, Any]:
        node: dict[str, Any] = {
            "@type": self.kind,
            "@id": self.entity_id,
            "name": self.name,
        }
        if self.url:
            node["url"] = self.url
        if self.same_as:
            node["sameAs"] = list(self.same_as)
        return node

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "kind": self.kind,
            "same_as": list(self.same_as),
            "url": self.url,
        }


@dataclass
class SchemaStack:
    graph: list[dict[str, Any]]

    def as_script_tag(self) -> str:
        """Return the JSON-LD string ready to drop into a
        ``<script type="application/ld+json">`` tag."""
        payload = {
            "@context": "https://schema.org",
            "@graph": self.graph,
        }
        return json.dumps(
            payload, separators=(",", ":"),
        )

    def types(self) -> tuple[str, ...]:
        return tuple(
            str(n.get("@type") or "") for n in self.graph
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "graph": list(self.graph),
            "type_count": len(
                {str(n.get("@type")) for n in self.graph},
            ),
        }


def _product_id(handle: str) -> str:
    return f"#product-{handle}"


def _offer_id(handle: str) -> str:
    return f"#offer-{handle}"


def _brand_id(handle: str) -> str:
    return f"#brand-{handle}"


def _rating_id(handle: str) -> str:
    return f"#rating-{handle}"


def _faq_id(handle: str) -> str:
    return f"#faq-{handle}"


def _howto_id(handle: str) -> str:
    return f"#howto-{handle}"


def _video_id(handle: str) -> str:
    return f"#video-{handle}"


def _crumbs_id(handle: str) -> str:
    return f"#crumbs-{handle}"


def _org_id() -> str:
    return "#organization"


def build_schema_stack(
    product: dict[str, Any],
    *,
    site_url: str,
    author: AuthorEntity,
    organization: dict[str, Any] | None = None,
    faqs: list[dict[str, str]] | None = None,
    howto_steps: list[str] | None = None,
    video: dict[str, str] | None = None,
    breadcrumbs: list[dict[str, str]] | None = None,
) -> SchemaStack:
    """Return a schema.org @graph containing every applicable
    type for the product.

    ``product`` required keys: title, handle.
    Everything else optional and produces a richer graph as you
    feed more data in. Zero-data case still emits Product +
    Offer + Organization so the page has ≥3 types.
    """
    if not product.get("title"):
        raise ValueError("product.title required")
    handle = str(
        product.get("handle")
        or product.get("url")
        or product.get("title", "p"),
    ).lower().replace(" ", "-")
    base = (site_url or "").rstrip("/")
    product_url = (
        f"{base}/products/{handle}" if base else handle
    )

    graph: list[dict[str, Any]] = []

    # 1. Organization — publisher entity for E-E-A-T
    org_node: dict[str, Any] = {
        "@type": "Organization",
        "@id": _org_id(),
        "name": (
            (organization or {}).get("name")
            or author.name
        ),
    }
    org_url = (organization or {}).get("url") or base
    if org_url:
        org_node["url"] = org_url
    org_same_as = (organization or {}).get("same_as") or []
    if org_same_as:
        org_node["sameAs"] = list(org_same_as)
    graph.append(org_node)

    # 2. Product
    product_node: dict[str, Any] = {
        "@type": "Product",
        "@id": _product_id(handle),
        "name": str(product.get("title", "")),
        "description": str(
            product.get("description", ""),
        )[:5000],
        "url": product_url,
        "sku": str(product.get("sku", "")),
        "brand": {
            "@id": _brand_id(handle),
        },
        "offers": {
            "@id": _offer_id(handle),
        },
        "author": {"@id": author.entity_id},
    }
    image = str(product.get("image", "") or "")
    if image:
        product_node["image"] = image
    rating_value = product.get("rating")
    review_count = product.get("review_count")
    if rating_value is not None and review_count:
        product_node["aggregateRating"] = {
            "@id": _rating_id(handle),
        }
    graph.append(product_node)

    # 3. Brand — explicit node so Knowledge Graph resolves
    brand_node = {
        "@type": "Brand",
        "@id": _brand_id(handle),
        "name": str(
            product.get("brand") or author.name,
        ),
    }
    graph.append(brand_node)

    # 4. Offer
    price = float(product.get("price", 0) or 0)
    currency = str(product.get("currency", "USD"))
    availability = str(
        product.get("availability", "InStock"),
    )
    offer_node = {
        "@type": "Offer",
        "@id": _offer_id(handle),
        "price": f"{price:.2f}",
        "priceCurrency": currency,
        "availability": (
            f"https://schema.org/{availability}"
        ),
        "url": product_url,
    }
    graph.append(offer_node)

    # 5. AggregateRating (only when we have review data)
    if rating_value is not None and review_count:
        try:
            rv = float(rating_value)
            rc = int(review_count)
            graph.append({
                "@type": "AggregateRating",
                "@id": _rating_id(handle),
                "ratingValue": f"{rv:.1f}",
                "reviewCount": rc,
            })
        except (TypeError, ValueError):
            pass

    # 6. FAQPage
    if faqs:
        faq_node = {
            "@type": "FAQPage",
            "@id": _faq_id(handle),
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": str(q.get("q", "")),
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": str(q.get("a", "")),
                    },
                }
                for q in faqs if q.get("q")
            ],
        }
        graph.append(faq_node)

    # 7. HowTo — useful for assembly / usage content
    if howto_steps:
        graph.append({
            "@type": "HowTo",
            "@id": _howto_id(handle),
            "name": (
                f"How to use {product.get('title', '')}"
            ),
            "step": [
                {
                    "@type": "HowToStep",
                    "position": i + 1,
                    "text": str(step),
                }
                for i, step in enumerate(howto_steps)
                if step
            ],
        })

    # 8. VideoObject — product video embed
    if video and video.get("content_url"):
        graph.append({
            "@type": "VideoObject",
            "@id": _video_id(handle),
            "name": str(
                video.get(
                    "name", product.get("title", ""),
                ),
            ),
            "description": str(
                video.get("description", ""),
            ),
            "uploadDate": str(
                video.get("upload_date", ""),
            ),
            "contentUrl": str(video["content_url"]),
            "thumbnailUrl": str(
                video.get("thumbnail_url", ""),
            ),
        })

    # 9. BreadcrumbList
    if breadcrumbs:
        graph.append({
            "@type": "BreadcrumbList",
            "@id": _crumbs_id(handle),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "name": str(b.get("name", "")),
                    "item": str(b.get("url", "")),
                }
                for i, b in enumerate(breadcrumbs)
                if b.get("name")
            ],
        })

    # 10. Author entity dereferenced once at the end
    graph.append(author.as_jsonld())

    return SchemaStack(graph=graph)
