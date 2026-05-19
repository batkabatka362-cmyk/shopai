"""Niche-aware smart collection rule generator.

``collection_seeder`` (PR #370) ships MANUAL starter
collections -- empty title-only buckets the operator has to
manually fill from product inventory. That works for static
"Best Sellers" / "Gift Sets" buckets but is wrong for the
rule-driven collections every Shopify store needs:

  * "Under $50" -- auto-includes anything below a price.
  * "On Sale" -- auto-includes products tagged ``sale``.
  * "New Arrivals" -- auto-includes products created in
    the last 30 days.
  * "In Stock" -- auto-excludes sold-out items.
  * Niche-specific: "Vegan & Cruelty-Free" (beauty),
    "Bridal" (jewelry), "Trail-Ready" (outdoor), ...

This module ships those rule sets per niche, ready to feed
into ``SHOPIFY_CREATE_COLLECTION`` with the ``rule_set``
arg. Smart collections auto-populate as products are
added / tagged / priced -- zero ongoing maintenance.

Return shape from :func:`generate_smart_collections`::

    {
        "store_name": "Acme Beauty",
        "niche": "beauty",
        "collections": [
            {
                "title": "On Sale",
                "handle": "on-sale",
                "description_html": "<p>Products...</p>",
                "rule_set": {
                    "applied_disjunctively": False,
                    "rules": [
                        {"column": "TAG",
                         "relation": "EQUALS",
                         "condition": "sale"},
                    ],
                },
                "sort_order": "BEST_SELLING",
            },
            ...
        ],
    }

Each entry is drop-in for ``apply_starter_collections`` in
``collection_seeder.py`` -- callers use the same applier.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Universal rule sets ──────────────────────────────────────


# Each tuple: (title, description_html, rules, sort_order).
# `applied_disjunctively=False` (AND between rules) is the
# default; flipped per spec when OR semantics are needed.
_UNIVERSAL_COLLECTIONS: list[
    tuple[str, str, list[dict[str, Any]], str]
] = [
    (
        "New Arrivals",
        "<p>Latest additions to the store -- last 30 "
        "days.</p>",
        [
            {
                "column": "PRODUCT_CREATED_AT",
                "relation": "GREATER_THAN",
                "condition": "30 days ago",
            },
        ],
        "CREATED",
    ),
    (
        "On Sale",
        "<p>Discounted styles. Limited stock.</p>",
        [
            {
                "column": "TAG",
                "relation": "EQUALS",
                "condition": "sale",
            },
        ],
        "BEST_SELLING",
    ),
    (
        "In Stock",
        "<p>Ready to ship -- excludes sold-out items.</p>",
        [
            {
                "column": "VARIANT_INVENTORY",
                "relation": "GREATER_THAN",
                "condition": "0",
            },
        ],
        "BEST_SELLING",
    ),
    (
        "Under $50",
        "<p>Pieces priced below $50.</p>",
        [
            {
                "column": "VARIANT_PRICE",
                "relation": "LESS_THAN",
                "condition": "50",
            },
        ],
        "PRICE_ASC",
    ),
]


# Niche-specific rule sets. Tag-based filters that depend on
# the store_setup.tag_library taxonomy -- when those tags
# are applied by the auto_tagger (PR #387), these
# collections auto-populate.
_NICHE_COLLECTIONS: dict[
    str, list[tuple[
        str, str, list[dict[str, Any]], str,
    ]],
] = {
    "beauty": [
        (
            "Vegan & Cruelty-Free",
            "<p>Beauty products tagged vegan + "
            "cruelty-free.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "claims:vegan",
                },
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "claims:cruelty-free",
                },
            ],
            "BEST_SELLING",
        ),
        (
            "For Sensitive Skin",
            "<p>Curated for sensitive skin types.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "skin-type:sensitive",
                },
            ],
            "BEST_SELLING",
        ),
    ],
    "fashion": [
        (
            "Sustainable Fabrics",
            "<p>Pieces made from natural-fibre "
            "fabrics.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "fabric:cotton",
                },
            ],
            "BEST_SELLING",
        ),
        (
            "Plus Size",
            "<p>Inclusive fits sized for every body.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "fit-type:plus",
                },
            ],
            "BEST_SELLING",
        ),
    ],
    "tech": [
        (
            "Premium Tier",
            "<p>Premium tech -- $250 and up.</p>",
            [
                {
                    "column": "VARIANT_PRICE",
                    "relation": "GREATER_THAN",
                    "condition": "250",
                },
            ],
            "BEST_SELLING",
        ),
        (
            "Wireless",
            "<p>Untethered tech -- audio, charging, "
            "input devices.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "feature:wireless",
                },
            ],
            "BEST_SELLING",
        ),
    ],
    "home": [
        (
            "Sustainable Home",
            "<p>Pieces tagged sustainable + "
            "handmade.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "claims:sustainable",
                },
            ],
            "BEST_SELLING",
        ),
    ],
    "food": [
        (
            "Gluten-Free",
            "<p>Pantry + treats tagged gluten-free.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "diet:gluten-free",
                },
            ],
            "BEST_SELLING",
        ),
        (
            "Vegan",
            "<p>100% plant-based selection.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "diet:vegan",
                },
            ],
            "BEST_SELLING",
        ),
    ],
    "pets": [
        (
            "Grain-Free Foods",
            "<p>Grain-free food + treats for sensitive "
            "stomachs.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "claims:grain-free",
                },
            ],
            "BEST_SELLING",
        ),
        (
            "For Puppies",
            "<p>Age-appropriate food, toys + gear.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "life-stage:puppy",
                },
            ],
            "BEST_SELLING",
        ),
    ],
    "fitness": [
        (
            "Third-Party Tested Supplements",
            "<p>Supplements with batch-level lab "
            "testing.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": (
                        "claims:third-party-tested"
                    ),
                },
            ],
            "BEST_SELLING",
        ),
        (
            "Compression Apparel",
            "<p>Compression-fit shirts, shorts + "
            "tights.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "fit:compression",
                },
            ],
            "BEST_SELLING",
        ),
    ],
    "jewelry": [
        (
            "Sterling Silver",
            "<p>Pieces crafted in solid sterling "
            "silver.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "metal:sterling-silver",
                },
            ],
            "BEST_SELLING",
        ),
        (
            "Bridal + Engagement",
            "<p>Heirloom-quality bridal + engagement "
            "pieces.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "category:bridal",
                },
            ],
            "BEST_SELLING",
        ),
    ],
    "outdoor": [
        (
            "Waterproof",
            "<p>Gear rated waterproof -- shells, "
            "boots, packs.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "weather:waterproof",
                },
            ],
            "BEST_SELLING",
        ),
        (
            "Ultralight",
            "<p>Sub-ounce-counts for fast-and-light "
            "trips.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "weight-class:ultralight",
                },
            ],
            "BEST_SELLING",
        ),
    ],
    "baby": [
        (
            "Organic Cotton",
            "<p>OEKO-TEX / GOTS certified organic "
            "cotton pieces.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "material:organic-cotton",
                },
            ],
            "BEST_SELLING",
        ),
        (
            "0-3 Months",
            "<p>For the smallest stage.</p>",
            [
                {
                    "column": "TAG",
                    "relation": "EQUALS",
                    "condition": "age-stage:0-3mo",
                },
            ],
            "BEST_SELLING",
        ),
    ],
    "general": [],
}


def _slug(title: str) -> str:
    """Title -> URL handle. Lowercase + hyphen-separated."""
    s = (title or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "collection"


def generate_smart_collections(
    *,
    niche: str = "general",
) -> dict[str, Any]:
    """Build niche-aware smart-collection specs.

    Args:
        niche: Lowercase niche key. Unknown -> general
            (universal-only).

    Returns:
        ``{niche, collections: [...]}``. Each collection
        is drop-in for
        ``collection_seeder.apply_starter_collections``.
    """
    niche_n = (niche or "general").strip().lower() or "general"
    niche_entries = _NICHE_COLLECTIONS.get(niche_n, [])

    out: list[dict[str, Any]] = []
    for title, description, rules, sort_order in (
        _UNIVERSAL_COLLECTIONS + niche_entries
    ):
        # `applied_disjunctively=True` (OR semantics) when
        # there are multiple rules and the niche-specific
        # collection has explicit multi-tag union intent
        # (e.g. vegan + cruelty-free). We use the
        # heuristic: 2+ TAG=EQUALS rules with same column ->
        # AND of all (i.e. ALL tags must match). Otherwise
        # default AND.
        out.append({
            "title": title,
            "handle": _slug(title),
            "description_html": description,
            "sort_order": sort_order,
            "rule_set": {
                "applied_disjunctively": False,
                "rules": [dict(r) for r in rules],
            },
        })

    return {
        "niche": niche_n,
        "collections": out,
    }
