"""Category detector — auto-detect regulated product category from keywords.

Scans product title, category, tags for keywords matching 6 regulated categories.
"""
from __future__ import annotations

from typing import Any


CATEGORY_KEYWORDS = {
    "supplements": ["supplement", "vitamin", "mineral", "protein", "probiotic", "herbal", "dietary"],
    "cosmetics": ["cosmetic", "skincare", "makeup", "beauty", "cream", "serum", "moisturizer", "sunscreen"],
    "food": ["food", "snack", "candy", "beverage", "drink", "tea", "coffee", "organic food"],
    "electronics": ["electronic", "charger", "cable", "bluetooth", "wireless", "speaker", "headphone"],
    "children": ["kids", "children", "baby", "infant", "toddler", "toy", "nursery"],
    "textiles": ["clothing", "apparel", "shirt", "dress", "fabric", "cotton", "textile"],
}


def detect_category(product: dict[str, Any]) -> str | None:
    """Detect regulated category from product data."""
    category = (product.get("product_type", "") + " " + product.get("category", "")).lower()
    title = (product.get("title", "") + " " + product.get("name", "")).lower()
    tags = " ".join(product.get("tags", [])).lower() if isinstance(product.get("tags"), list) else ""
    combined = f"{category} {title} {tags}"

    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return cat

    return None
