"""Catalog Engine — category organizer.

Organizes products into category hierarchy based on
product attributes, existing categories, and auto-detection.
"""
from __future__ import annotations

import copy
from typing import Any


def organize_categories(
    products: list[dict[str, Any]],
    categories: list[dict[str, Any]],
) -> dict[str, Any]:
    """Organize products into categories.

    Args:
        products: Product records.
        categories: Existing category definitions.

    Returns:
        Structured dict with category organization.
    """
    try:
        prods = copy.deepcopy(products)
        cats = copy.deepcopy(categories)

        # Build category map from existing
        cat_map: dict[str, dict[str, Any]] = {}
        for cat in cats:
            name = str(cat.get("name", cat.get("id", "uncategorized")))
            cat_map[name] = {
                "name": name,
                "parent": cat.get("parent"),
                "products": [],
            }

        # Assign products to categories
        uncategorized: list[dict[str, Any]] = []

        for prod in prods:
            pid = str(prod.get("id", ""))
            prod_cat = str(prod.get("category", prod.get("product_type", "")))

            if prod_cat and prod_cat in cat_map:
                cat_map[prod_cat]["products"].append(pid)
            elif prod_cat:
                cat_map[prod_cat] = {
                    "name": prod_cat,
                    "parent": None,
                    "products": [pid],
                }
            else:
                uncategorized.append(prod)

        if uncategorized:
            cat_map["uncategorized"] = {
                "name": "uncategorized",
                "parent": None,
                "products": [str(p.get("id", "")) for p in uncategorized],
            }

        organized: dict[str, Any] = {}
        for name, cat_data in cat_map.items():
            organized[name] = {
                "product_count": len(cat_data["products"]),
                "products": cat_data["products"],
                "parent": cat_data.get("parent"),
            }

        return {
            "status": "success",
            "categories": organized,
            "total_categories": len(organized),
            "uncategorized_count": len(uncategorized),
        }
    except Exception as exc:
        return {
            "status": "error",
            "categories": {},
            "error": f"Category organization failed: {exc}",
        }
