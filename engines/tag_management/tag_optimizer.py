"""Tag Management Engine — tag optimizer.

Optimizes tag coverage: identifies redundant tags, suggests
merges, flags under-tagged products, and recommends tag limits.
"""
from __future__ import annotations

import copy
from typing import Any


def optimize_tags(
    tag_assignments: list[dict[str, Any]],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    """Optimize tag assignments.

    Args:
        tag_assignments: Current tag assignments.
        taxonomy: Taxonomy tree.

    Returns:
        Structured dict with optimization suggestions.
    """
    try:
        assignments = copy.deepcopy(tag_assignments)
        suggestions: list[str] = []

        # Tag frequency analysis
        tag_freq: dict[str, int] = {}
        for a in assignments:
            for tag in a.get("tags", []):
                tag_freq[tag] = tag_freq.get(tag, 0) + 1

        total_products = len(assignments)

        # Identify rare tags (used by < 2% of products)
        rare_tags = [t for t, f in tag_freq.items() if f < max(1, total_products * 0.02)]
        if rare_tags:
            suggestions.append(f"Consider removing {len(rare_tags)} rare tags used by <2% of products: {', '.join(rare_tags[:5])}")

        # Identify over-tagged products (> 15 tags)
        over_tagged = [a for a in assignments if len(a.get("tags", [])) > 15]
        if over_tagged:
            suggestions.append(f"{len(over_tagged)} products have >15 tags — consider reducing to improve relevance")

        # Identify under-tagged products (< 2 tags)
        under_tagged = [a for a in assignments if len(a.get("tags", [])) < 2]
        if under_tagged:
            suggestions.append(f"{len(under_tagged)} products have <2 tags — add more for better discoverability")

        # Identify universal tags (used by >80% of products)
        universal = [t for t, f in tag_freq.items() if f > total_products * 0.8]
        if universal:
            suggestions.append(f"Tags used by >80% of products add no value: {', '.join(universal)}")

        if not suggestions:
            suggestions.append("Tag coverage is well balanced — no optimizations needed")

        return {
            "status": "success",
            "suggestions": suggestions,
            "stats": {
                "total_unique_tags": len(tag_freq),
                "rare_tags_count": len(rare_tags),
                "over_tagged_count": len(over_tagged),
                "under_tagged_count": len(under_tagged),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "suggestions": [],
            "error": f"Tag optimization failed: {exc}",
        }
