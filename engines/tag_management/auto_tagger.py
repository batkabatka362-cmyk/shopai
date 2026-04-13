"""Tag Management Engine — auto tagger.

Auto-generates tags from product data: title keywords,
category mapping, attribute extraction, and price tier.
"""
from __future__ import annotations

import copy
import re
from typing import Any


_STOP_WORDS = {"the", "a", "an", "and", "or", "for", "in", "on", "of", "to", "with", "is", "it"}


def auto_tag(
    products: list[dict[str, Any]],
    existing_tags: list[str],
) -> dict[str, Any]:
    """Auto-generate tags for products.

    Args:
        products: Product records.
        existing_tags: Currently known tags.

    Returns:
        Structured dict with auto-generated tag assignments.
    """
    try:
        prods = copy.deepcopy(products)
        known = set(t.lower() for t in existing_tags)
        assignments: list[dict[str, Any]] = []
        new_tags: set[str] = set()

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
