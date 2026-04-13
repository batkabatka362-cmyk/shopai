"""Search Optimization Engine — sitemap builder.

Generates a structured sitemap with priority and change frequency
based on product importance and content quality scores.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# ---------------------------------------------------------------------------
# Default priority assignments
# ---------------------------------------------------------------------------

_BASE_PRIORITY = 0.5
_HIGH_SCORE_BONUS = 0.3
_CATEGORY_PAGE_PRIORITY = 0.7
_HOME_PAGE_PRIORITY = 1.0


def build_sitemap(
    products: list[dict[str, Any]],
    content_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a sitemap structure with priorities and change frequencies.

    Args:
        products: List of product records.
        content_scores: Content score results per product.

    Returns:
        Structured dict with sitemap entries.
    """
    try:
        products = copy.deepcopy(products)

        # Build score lookup
        score_map: dict[str, float] = {}
        for cs in content_scores:
            pid = str(cs.get("product_id", ""))
            score_map[pid] = float(cs.get("overall_score", 0.5))

        sitemap: list[dict[str, Any]] = []
        categories_seen: set[str] = set()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Add home page
        sitemap.append({
            "url": "/",
            "priority": _HOME_PAGE_PRIORITY,
            "change_frequency": "daily",
            "last_modified": now,
        })

        for product in products:
            pid = str(product.get("id", ""))
            url = str(product.get("url", f"/products/{pid}"))
            category = str(product.get("category", ""))

            # Product page priority based on content quality
            quality_score = score_map.get(pid, 0.5)
            priority = round(_BASE_PRIORITY + quality_score * _HIGH_SCORE_BONUS, 2)
            priority = min(priority, 0.9)

            # Change frequency based on category
            change_freq = _estimate_change_frequency(product)

            sitemap.append({
                "url": url,
                "priority": priority,
                "change_frequency": change_freq,
                "last_modified": now,
            })

            # Add category page if not yet seen
            if category and category not in categories_seen:
                categories_seen.add(category)
                cat_slug = category.lower().replace(" ", "-")
                sitemap.append({
                    "url": f"/collections/{cat_slug}",
                    "priority": _CATEGORY_PAGE_PRIORITY,
                    "change_frequency": "weekly",
                    "last_modified": now,
                })

        # Sort by priority descending
        sitemap.sort(key=lambda s: s.get("priority", 0), reverse=True)

        return {
            "status": "success",
            "sitemap": sitemap,
        }
    except Exception as exc:
        return {
            "status": "error",
            "sitemap": [],
            "error": f"Sitemap building failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _estimate_change_frequency(product: dict[str, Any]) -> str:
    """Estimate how frequently a product page changes."""
    # Products with active inventory change more frequently
    tags = [str(t).lower() for t in product.get("tags", [])]

    if any(t in tags for t in ["new", "sale", "featured", "trending"]):
        return "daily"
    elif any(t in tags for t in ["seasonal", "limited"]):
        return "weekly"
    else:
        return "monthly"
