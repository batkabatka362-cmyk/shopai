"""Niche-aware product tag taxonomy.

Existing `engines.tag_management.auto_tagger` derives tags
from product data (title keywords, category, price tier,
attribute fields). It's good at "what's in the product
record"; it's blind to "what tag set does this niche use".

Result: a beauty store ends up with tags like
``["serum", "30", "ml", "premium"]`` -- title keywords --
when what makes a beauty store filterable is structured
tags like ``["skin-type:dry", "concern:hydration",
"texture:gel", "vegan", "fragrance-free"]``.

This module is the reference taxonomy. For each niche it
returns the **canonical tag families** the niche uses for
filtering, faceting, and segment-building. A
:func:`suggest_tags_for_product` helper combines the niche
taxonomy with the product's own data to surface
tag suggestions for the operator (or for the existing
auto_tagger to incorporate).

Read-only -- no Shopify writes; pure reference data
consumed by other engines. Treat it like a config file
with helpers.

Return shape from :func:`get_niche_tags`::

    {
        "niche": "beauty",
        "families": {
            "skin-type":  ["oily", "dry", "combination",
                           "sensitive", "all-types"],
            "concern":    ["hydration", "anti-aging",
                           "brightening", ...],
            "texture":    ["gel", "cream", "oil", ...],
            "claims":     ["vegan", "cruelty-free",
                           "fragrance-free", ...],
        },
    }

Each family is a flat list of slug-cased tag values. The
prefix-colon convention (``skin-type:dry``) is the Shopify
filter convention so themes can render faceted nav
automatically.
"""
from __future__ import annotations

import re
from typing import Any, Iterable


# Niche-specific tag families. Each family carries a list of
# slug-cased values that map directly to Shopify product
# tags using the ``family:value`` convention (Shopify's
# native facet syntax).
#
# Coverage philosophy:
#   * Every value should be something a customer would
#     actually filter on.
#   * No values that are already covered by Shopify's
#     built-in filters (price, availability).
#   * Mix of attributes (objective) and concerns / claims
#     (subjective but searchable).
_NICHE_TAG_FAMILIES: dict[str, dict[str, list[str]]] = {
    "beauty": {
        "skin-type": [
            "oily", "dry", "combination", "sensitive",
            "all-types",
        ],
        "concern": [
            "hydration", "anti-aging", "brightening",
            "blemishes", "redness", "uneven-tone",
            "fine-lines",
        ],
        "texture": [
            "gel", "cream", "oil", "serum", "balm",
            "foam", "lotion",
        ],
        "claims": [
            "vegan", "cruelty-free", "fragrance-free",
            "non-comedogenic", "dermatologist-tested",
            "reef-safe",
        ],
        "ingredient-highlight": [
            "vitamin-c", "retinol", "niacinamide",
            "hyaluronic-acid", "ceramides", "peptides",
            "spf",
        ],
    },
    "fashion": {
        "fit": [
            "slim", "regular", "relaxed", "oversized",
            "tailored",
        ],
        "fabric": [
            "cotton", "linen", "wool", "silk",
            "denim", "leather", "synthetic-blend",
        ],
        "occasion": [
            "everyday", "work", "evening", "weekend",
            "travel",
        ],
        "season": [
            "spring", "summer", "fall", "winter",
            "all-season",
        ],
        "fit-type": [
            "petite", "regular", "tall", "plus",
        ],
        "claims": [
            "made-in", "ethical-production",
            "natural-fibres", "machine-washable",
        ],
    },
    "tech": {
        "category": [
            "audio", "wearables", "smart-home",
            "accessories", "cables-power", "gaming",
        ],
        "compatibility": [
            "ios", "android", "windows", "macos",
            "cross-platform",
        ],
        "feature": [
            "wireless", "fast-charging", "noise-cancelling",
            "waterproof", "voice-control", "ai-enabled",
        ],
        "price-tier": [
            "budget", "mid-range", "premium", "flagship",
        ],
        "warranty": [
            "1-year", "2-year", "3-year", "5-year",
            "lifetime",
        ],
    },
    "home": {
        "room": [
            "kitchen", "bedroom", "living-room",
            "bathroom", "outdoor", "office",
        ],
        "material": [
            "wood", "metal", "ceramic", "glass",
            "textile", "stone", "concrete",
        ],
        "style": [
            "minimalist", "scandinavian", "industrial",
            "rustic", "modern", "traditional",
        ],
        "function": [
            "storage", "lighting", "seating", "decor",
            "tableware",
        ],
        "claims": [
            "handmade", "sustainable", "fair-trade",
            "small-batch",
        ],
    },
    "food": {
        "diet": [
            "vegan", "vegetarian", "gluten-free",
            "dairy-free", "keto", "paleo", "halal",
            "kosher",
        ],
        "category": [
            "pantry", "drinks", "snacks", "sweets",
            "savoury", "sauces", "spices",
        ],
        "origin": [
            "local", "imported", "single-origin",
            "small-batch", "fair-trade",
        ],
        "preservation": [
            "shelf-stable", "refrigerated", "frozen",
        ],
        "occasion": [
            "everyday", "gift", "entertaining",
            "subscription",
        ],
    },
    "pets": {
        "species": [
            "dog", "cat", "small-pet", "bird", "fish",
        ],
        "life-stage": [
            "puppy", "kitten", "adult", "senior",
            "all-stages",
        ],
        "category": [
            "food", "treats", "toys", "grooming",
            "beds", "harnesses", "supplements",
        ],
        "size": [
            "small", "medium", "large", "extra-large",
        ],
        "claims": [
            "grain-free", "single-protein", "vet-approved",
            "made-in", "no-fillers",
        ],
    },
    "fitness": {
        "activity": [
            "running", "weight-training", "yoga",
            "crossfit", "cycling", "swimming",
        ],
        "category": [
            "apparel", "equipment", "supplements",
            "recovery", "accessories",
        ],
        "size": [
            "xs", "s", "m", "l", "xl", "xxl",
        ],
        "fit": [
            "compression", "regular", "relaxed",
        ],
        "claims": [
            "moisture-wicking", "anti-microbial",
            "third-party-tested", "transparent-label",
        ],
    },
    "jewelry": {
        "category": [
            "necklaces", "earrings", "rings", "bracelets",
            "bridal",
        ],
        "metal": [
            "sterling-silver", "14k-gold", "18k-gold",
            "titanium", "platinum", "gold-vermeil",
        ],
        "stone": [
            "diamond", "sapphire", "ruby", "emerald",
            "pearl", "no-stone", "lab-grown",
        ],
        "style": [
            "minimalist", "statement", "vintage",
            "modern", "heirloom",
        ],
        "claims": [
            "ethically-sourced", "conflict-free",
            "handmade", "engraveable",
        ],
    },
    "outdoor": {
        "activity": [
            "camping", "hiking", "climbing", "skiing",
            "paddling", "running",
        ],
        "season": [
            "3-season", "4-season", "winter",
            "all-season",
        ],
        "weather": [
            "waterproof", "water-resistant",
            "wind-blocking", "breathable", "insulated",
        ],
        "category": [
            "apparel", "footwear", "shelter",
            "sleep-systems", "packs", "cooking",
        ],
        "weight-class": [
            "ultralight", "lightweight",
            "standard-weight",
        ],
    },
    "baby": {
        "age-stage": [
            "0-3mo", "3-6mo", "6-12mo", "12-24mo",
            "2-3y",
        ],
        "category": [
            "clothing", "nursery", "feeding",
            "toys", "books", "safety",
        ],
        "material": [
            "organic-cotton", "bamboo", "wool",
            "hypoallergenic", "bpa-free", "non-toxic",
        ],
        "claims": [
            "oeko-tex", "gots-certified", "cpsia-compliant",
            "machine-washable",
        ],
        "use": [
            "everyday", "gift", "first-baby",
            "second-baby",
        ],
    },
    "general": {
        "category": [
            "new-arrivals", "best-sellers", "sale",
            "gifts",
        ],
        "price-tier": [
            "under-25", "25-50", "50-100",
            "over-100",
        ],
        "occasion": [
            "everyday", "gift", "limited-edition",
        ],
    },
}


# Each niche supports these CORE families. Used by the
# coverage assertion in tests + by callers that need a
# "what families does this niche use" hint.
def get_niche_tags(
    niche: str = "general",
) -> dict[str, Any]:
    """Return the canonical tag taxonomy for a niche.

    Args:
        niche: Lowercase niche key. Unknown niches fall back
            to ``general``.

    Returns:
        ``{niche, families: {family_name: [values, ...]}}``.
    """
    niche_n = (niche or "general").strip().lower() or "general"
    families = _NICHE_TAG_FAMILIES.get(
        niche_n, _NICHE_TAG_FAMILIES["general"],
    )
    return {
        "niche": niche_n,
        "families": {
            k: list(v) for k, v in families.items()
        },
    }


def flatten_to_tags(
    families: dict[str, list[str]],
    *,
    include_prefix: bool = True,
) -> list[str]:
    """Flatten a families dict to a list of tag strings.

    Args:
        families: ``{family_name: [values]}`` -- typically
            ``get_niche_tags(niche)["families"]``.
        include_prefix: When True (default), every tag is
            prefixed with its family name + colon
            (``skin-type:dry``). This is the Shopify native
            filter convention. When False, returns bare
            values (``dry``).

    Returns:
        Deduplicated list of tag strings. Empty input -> [].
    """
    if not isinstance(families, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for family, values in families.items():
        if not isinstance(values, list):
            continue
        for v in values:
            if not isinstance(v, str) or not v.strip():
                continue
            tag = (
                f"{family}:{v.strip().lower()}"
                if include_prefix
                else v.strip().lower()
            )
            if tag not in seen:
                out.append(tag)
                seen.add(tag)
    return out


def suggest_tags_for_product(
    product: dict[str, Any],
    *,
    niche: str = "general",
    max_per_family: int = 2,
) -> list[str]:
    """Suggest niche-appropriate tags for a single product.

    Combines the niche's canonical tag families with hints
    from the product's own data (title, description, tags,
    product_type, vendor) using simple keyword matching.
    Returns the matches as ``family:value`` strings.

    Args:
        product: Product dict in the friendly shape
            ``SHOPIFY_LIST_PRODUCTS`` emits.
        niche: Lowercase niche key.
        max_per_family: Cap suggestions per family so the
            tag count stays reasonable even when many
            keywords match (default 2).

    Returns:
        Deduplicated list of ``family:value`` tags. Empty
        list when product has no extractable signal.
    """
    if not isinstance(product, dict):
        return []
    niche_n = (niche or "general").strip().lower() or "general"
    families = _NICHE_TAG_FAMILIES.get(
        niche_n, _NICHE_TAG_FAMILIES["general"],
    )

    # Build a haystack from all the product's text fields.
    haystack = _build_haystack(product).lower()
    if not haystack:
        return []

    suggestions: list[str] = []
    seen: set[str] = set()
    for family, values in families.items():
        family_hits = 0
        for value in values:
            if family_hits >= max(0, int(max_per_family)):
                break
            # Match either the slug ("anti-aging") or the
            # un-hyphenated form ("anti aging") in the
            # haystack -- products often spell these out.
            needles = {
                value.lower(),
                value.lower().replace("-", " "),
                value.lower().replace("-", ""),
            }
            if any(n in haystack for n in needles if n):
                tag = f"{family}:{value.lower()}"
                if tag not in seen:
                    suggestions.append(tag)
                    seen.add(tag)
                    family_hits += 1

    return suggestions


def _build_haystack(product: dict[str, Any]) -> str:
    """Concatenate every searchable text field into one
    blob for keyword matching."""
    parts: list[str] = []
    for key in (
        "title", "body_html", "description",
        "product_type", "vendor",
    ):
        val = product.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
    # tags can be list or comma string
    tags = product.get("tags")
    if isinstance(tags, list):
        parts.extend(
            str(t) for t in tags if isinstance(t, str)
        )
    elif isinstance(tags, str):
        parts.append(tags)
    # Strip HTML tags from body to avoid matching tag names.
    blob = " ".join(parts)
    blob = re.sub(r"<[^>]+>", " ", blob)
    return blob


def merge_suggested_with_existing(
    existing: Iterable[str] | None,
    suggested: Iterable[str] | None,
) -> list[str]:
    """Merge existing tags with suggested ones, deduped
    case-insensitively. Existing tags take order priority
    (the operator's choices win at the front of the list).

    Mirrors the merge convention used by
    `engines.tag_management.tag_applier` -- which is also
    case-insensitive and existing-wins. Reuse this helper
    when wiring tag suggestions into the auto-tagger so the
    merge stays consistent across the engine layer.
    """
    out: list[str] = []
    seen: set[str] = set()
    for source in (existing or []), (suggested or []):
        for tag in source:
            if not isinstance(tag, str):
                continue
            t = tag.strip()
            if not t:
                continue
            key = t.lower()
            if key in seen:
                continue
            out.append(t)
            seen.add(key)
    return out
