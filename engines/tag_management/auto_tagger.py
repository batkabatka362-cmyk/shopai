"""Tag Management Engine — auto tagger.

Auto-generates tags from product data: title keywords,
category mapping, attribute extraction, and price tier.

When a ``niche`` kwarg is supplied, the auto-tagger also
calls ``engines.store_setup.tag_library`` to surface
niche-appropriate ``family:value`` tags (e.g. ``vegan``,
``skin-type:dry``, ``activity:running``). Niche suggestions
are merged with the title-keyword extraction so the engine
output is both data-derived AND category-conventional.
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


_STOP_WORDS = {"the", "a", "an", "and", "or", "for", "in", "on", "of", "to", "with", "is", "it"}


def auto_tag(
    products: list[dict[str, Any]],
    existing_tags: list[str],
    *,
    niche: str | None = None,
) -> dict[str, Any]:
    """Auto-generate tags for products.

    Args:
        products: Product records.
        existing_tags: Currently known tags.
        niche: Optional niche key. When supplied (and the
            ``store_setup.tag_library`` module is available),
            niche-appropriate ``family:value`` tags are
            merged into each product's suggestion list.
            Unknown niches fall through to the general
            taxonomy; absent module / niche kwarg leaves
            behaviour unchanged from the pre-niche path.

    Returns:
        Structured dict with auto-generated tag assignments.
    """
    try:
        prods = copy.deepcopy(products)
        known = set(t.lower() for t in existing_tags)
        assignments: list[dict[str, Any]] = []
        new_tags: set[str] = set()
        niche_tagger = _resolve_niche_tagger(niche)

        for prod in prods:
            pid = str(prod.get("id", ""))
            title = str(prod.get("title", ""))
            desc = str(prod.get("description", ""))
            category = str(prod.get("category", ""))

            tags: list[str] = []

            # Extract keywords from title
            words = re.findall(r'\b[a-zA-Z]{3,}\b', title.lower())
            for word in words:
                if word not in _STOP_WORDS:
                    tags.append(word)
                    if word not in known:
                        new_tags.add(word)

            # Category tag
            if category:
                tags.append(category.lower())

            # Price tier
            price = float(prod.get("price", 0))
            if price > 0:
                if price < 20:
                    tags.append("affordable")
                elif price > 100:
                    tags.append("premium")

            # Material/color from attributes
            for attr_key in ("material", "color", "size", "brand"):
                val = prod.get(attr_key)
                if val:
                    tags.append(str(val).lower())

            # Niche-aware suggestions from the canonical
            # tag_library taxonomy.
            if niche_tagger is not None:
                try:
                    niche_tags = niche_tagger(prod)
                    for nt in niche_tags:
                        tags.append(nt)
                        if nt.lower() not in known:
                            new_tags.add(nt)
                except Exception as exc:  # noqa: BLE001
                    # Don't let the tag library poison the
                    # whole product's tag set if it raises.
                    logger.debug(
                        "auto_tag niche suggester raised "
                        "for %s: %s", pid, exc,
                    )

            # Deduplicate
            tags = list(dict.fromkeys(tags))

            assignments.append({
                "product_id": pid,
                "tags": tags,
            })

        return {
            "status": "success",
            "assignments": assignments,
            "new_tags_discovered": list(new_tags),
            "total_products_tagged": len(assignments),
        }
    except Exception as exc:
        return {
            "status": "error",
            "assignments": [],
            "error": f"Auto-tagging failed: {exc}",
        }


def _resolve_niche_tagger(niche: str | None):
    """Try to import the tag_library + bind a per-product
    suggester. Returns a callable or None.

    The lazy import means the tag_library is an optional
    dependency -- if store_setup is removed or shadowed,
    the auto-tagger falls back to its pre-niche behaviour.
    """
    if not niche or not isinstance(niche, str):
        return None
    niche_clean = niche.strip()
    if not niche_clean:
        return None
    try:
        from engines.store_setup.tag_library import (
            suggest_tags_for_product,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "auto_tag tag_library import failed: %s", exc,
        )
        return None

    def _suggest(product: dict[str, Any]) -> list[str]:
        return suggest_tags_for_product(
            product, niche=niche_clean,
        )

    return _suggest
