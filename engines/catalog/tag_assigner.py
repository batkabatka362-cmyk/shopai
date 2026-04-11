"""Catalog Engine — tag assigner.

Assigns tags to products based on attributes, category,
price tier, and keyword extraction from titles/descriptions.
"""
from __future__ import annotations

import copy
from typing import Any


def assign_tags(
    products: list[dict[str, Any]],
    available_tags: list[str],
) -> dict[str, Any]:
    """Assign tags to products.

    Args:
        products: Product records.
        available_tags: Pool of available tags.

    Returns:
        Structured dict with tag assignments.
    """
    try:
        prods = copy.deepcopy(products)
        tag_set = set(t.lower() for t in available_tags)
        assignments: list[dict[str, Any]] = []

        for prod in prods:
            pid = str(prod.get("id", ""))
            title = str(prod.get("title", "")).lower()
            desc = str(prod.get("description", "")).lower()
            category = str(prod.get("category", "")).lower()
            price = float(prod.get("price", 0))

            tags: list[str] = []

            # Category tag
            if category:
                tags.append(category)

            # Price tier tag
            if price > 0:
                if price < 25:
                    tags.append("budget")
                elif price < 100:
                    tags.append("mid-range")
                else:
                    tags.append("premium")

            # Match available tags against title/description
            text = f"{title} {desc}"
            for tag in tag_set:
                if tag in text and tag not in tags:
                    tags.append(tag)

            # Existing tags from product
            existing = prod.get("tags", [])
            if isinstance(existing, list):
                for t in existing:
                    if str(t).lower() not in [tg.lower() for tg in tags]:
                        tags.append(str(t))

            assignments.append({
                "product_id": pid,
                "tags": tags,
                "tag_count": len(tags),
            })

        total_tags = sum(a["tag_count"] for a in assignments)
        avg_tags = round(total_tags / len(assignments), 1) if assignments else 0.0

        return {
            "status": "success",
            "assignments": assignments,
            "total_assignments": len(assignments),
            "avg_tags_per_product": avg_tags,
        }
    except Exception as exc:
        return {
            "status": "error",
            "assignments": [],
            "error": f"Tag assignment failed: {exc}",
        }
